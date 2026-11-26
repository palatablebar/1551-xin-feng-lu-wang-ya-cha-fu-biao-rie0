from bisect import bisect_right
from collections import defaultdict
from collections.abc import Mapping
from math import fsum, isfinite, log, log1p

from .contracts import (Verification, Assessment, CalibrationRow, ModelReport,
                        CurveDecision, CurveSelection,
                        RISK_PROBABILITY_THRESHOLD, ZONE_CALIBRATION_MIN_SIZE)
from .slices import replay_slices


def clip_risk(number):
    return min(1-1e-12,max(1e-12,number))


def stable_loss(probability, outcome):
    clipped = clip_risk(probability)
    return -(log(clipped) if outcome==1 else log1p(-clipped))



def monotone_steps(blocks):
    selected = []
    for record in blocks:
        last, pressure, population = record
        while selected and pressure/population < selected[-1][1]/selected[-1][2]:
            _, failures, units = selected.pop()
            pressure += failures
            population += units
        selected.append((last,pressure,population))
    return tuple(edge for edge,_,_ in selected),tuple(level/count for _,level,count in selected)



def fan_power_cutpoints(checks):
    observations = defaultdict(list)
    for reading in checks:
        slot = min(4,int(reading.score*5))
        observations[slot].append(reading.outcome)
    prevalence = sum(item.outcome for item in checks) / len(checks)
    return monotone_steps(((slot+1)/5, sum(group)+2*prevalence, len(group)+2)
                          for slot,group in sorted(observations.items()))


def calibrated_fan_power_cutpoints(model, p):
    edges, bands = model
    return bands[min(len(bands)-1,bisect_right(edges,p))]


def prepare_verification(pairs, *, coverage=.85):
    confirmed = []
    positive = 0
    for gate in pairs:
        target = gate.outcome
        if target is None or not gate.observed:
            continue
        if not isfinite(gate.score) or target not in {0,1}:
            raise ValueError('异常度复核需有已确认的正常或异常标签')
        confirmed.append(gate)
        positive += target==1
    n = len(confirmed)
    if n>=8 and 0<positive<n:
        conversion = fan_power_cutpoints(confirmed)
        return Verification('fan_power_cutpoints',conversion,n,positive)
    return Verification('sparse-risk',(),n,positive)


def check_point(scored, anchor):
    if not isfinite(scored.score):
        raise ValueError('异常离差分已失效')
    outrank = clip_risk(scored.score)
    provisional = not anchor.parameters
    matched = outrank if provisional else calibrated_fan_power_cutpoints(anchor.parameters,outrank)
    return Assessment(scored,matched,None,None,provisional)


def validate_predictions(scored, prepared):
    # 向后兼容：单个 Verification 走原逻辑；传入分区选择或 {作业区: 曲线} 时按区取曲线。
    if isinstance(prepared, (CurveSelection, Mapping)) or hasattr(prepared, 'curve_for'):
        return validate_zone_predictions(scored, prepared)
    return tuple(map(lambda issue:check_point(issue,prepared),scored))


def _point_fields(point):
    """Return ``(cohort, outcome, observed)`` for predictions or assessments."""
    cohort = getattr(point, 'cohort', None)
    outcome = getattr(point, 'outcome', None)
    observed = getattr(point, 'observed', None)
    raw = getattr(point, 'raw', None)
    if raw is not None:
        if cohort is None:
            cohort = getattr(raw, 'cohort', None)
        if outcome is None:
            outcome = getattr(raw, 'outcome', None)
        raw_observed = getattr(raw, 'observed', None)
        if raw_observed is not None:
            observed = raw_observed
    if observed is None:
        observed = True
    return cohort, outcome, observed


def confirmed_points(points):
    """同一套“已确认实绩”口径：有 0/1 标签且未右截尾。"""
    confirmed = []
    for point in points:
        _, outcome, observed = _point_fields(point)
        if outcome is None or not observed or outcome not in (0, 1):
            continue
        confirmed.append(point)
    return confirmed


# 语义别名，兼容不同调用方对“已确认回放单”的命名。
confirmed_cases = confirmed_points
mature_points = confirmed_points


def group_by_cohort(points):
    groups = defaultdict(list)
    for point in points:
        cohort, _, _ = _point_fields(point)
        groups[cohort].append(point)
    return dict(groups)


def _probability_outcome(row):
    """从 Assessment / (概率, 实绩) / Mapping / Prediction 中取 (概率, 标签)。"""
    estimate = getattr(row, 'estimate', None)
    if estimate is not None:
        raw = getattr(row, 'raw', None)
        outcome = getattr(raw, 'outcome', None)
        if outcome is None:
            outcome = getattr(row, 'outcome', None)
        return estimate, outcome
    if isinstance(row, Mapping):
        probability = None
        for key in ('estimate', 'probability', 'risk', 'prediction', 'p', '预测概率', '概率', '估计'):
            if key in row:
                probability = row[key]
                break
        outcome = None
        for key in ('outcome', 'target', 'label', 'y', 'observed_outcome', '实绩', '标签'):
            if key in row:
                outcome = row[key]
                break
        return probability, outcome
    if isinstance(row, (tuple, list)) and len(row) >= 2:
        return row[0], row[1]
    return getattr(row, 'score', None), getattr(row, 'outcome', None)


def _finite_pairs(cases):
    pairs = []
    for case in cases:
        probability, outcome = _probability_outcome(case)
        if probability is None or outcome is None or outcome not in (0, 1):
            continue
        if not isfinite(probability):
            continue
        pairs.append((float(probability), int(outcome)))
    return pairs


def mean_squared_probability_error(cases):
    """均方概率误差（Brier 分数）；没有已确认样本时不作数值替代。"""
    pairs = _finite_pairs(cases)
    if not pairs:
        return None
    return fsum((probability-outcome)**2 for probability, outcome in pairs)/len(pairs)


# 常见同义命名。
mean_squared_error = mean_squared_probability_error
mean_squared_probability = mean_squared_probability_error
squared_probability_error = mean_squared_probability_error
probability_mse = mean_squared_probability_error
brier_score = mean_squared_probability_error
brier = mean_squared_probability_error


def missed_anomalies_at_threshold(cases, threshold=RISK_PROBABILITY_THRESHOLD):
    """原门槛下估计未超线的实绩异常数（与 boundary_diagnostics 的“漏查”同口径）。"""
    pairs = _finite_pairs(cases)
    return sum(1 for probability, outcome in pairs if outcome == 1 and probability < threshold)


miss_count = missed_anomalies_at_threshold
threshold_misses = missed_anomalies_at_threshold
count_misses = missed_anomalies_at_threshold
missed_anomaly_count = missed_anomalies_at_threshold
missed_anomalies = missed_anomalies_at_threshold
count_missed_anomalies = missed_anomalies_at_threshold
zone_miss_count = missed_anomalies_at_threshold


def _cohort_mapping(value):
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {key: list(rows) for key, rows in value.items()}
    return group_by_cohort(value)


def evaluate_curve_on_batch(curve, replay_batch, threshold=RISK_PROBABILITY_THRESHOLD):
    """在同一批已确认回放单上计算一条曲线的 MSE 与门槛漏异常数。"""
    assessed = [check_point(point, curve) for point in replay_batch]
    return {'assessments': tuple(assessed),
            'mse': mean_squared_probability_error(assessed),
            'misses': missed_anomalies_at_threshold(assessed, threshold)}


def compare_curves(global_curve, zone_curve, replay_batch,
                   threshold=RISK_PROBABILITY_THRESHOLD):
    """在同一批已确认区内回放单上比较全场/分区曲线并给出是否采用分区曲线。"""
    batch = confirmed_points(replay_batch)
    global_eval = evaluate_curve_on_batch(global_curve, batch, threshold)
    zone_eval = evaluate_curve_on_batch(zone_curve, batch, threshold)
    lower_mse = (zone_eval['mse'] is not None and global_eval['mse'] is not None
                 and zone_eval['mse'] < global_eval['mse'])
    no_extra_miss = zone_eval['misses'] <= global_eval['misses']
    adopt = bool(batch) and lower_mse and no_extra_miss
    return {'batch_size': len(batch),
            'global_mse': global_eval['mse'], 'zone_mse': zone_eval['mse'],
            'global_misses': global_eval['misses'], 'zone_misses': zone_eval['misses'],
            'lower_mse': lower_mse, 'no_extra_miss': no_extra_miss,
            'adopt': adopt, 'adopt_zone_curve': adopt,
            'use_zone_curve': adopt}


compare_calibration_curves = compare_curves
compare_zone_curves = compare_curves
curve_gate = compare_curves
replay_curve_gate = compare_curves


def choose_zone_curve(cohort, calibration_rows, replay_rows, global_curve,
                      *, threshold=RISK_PROBABILITY_THRESHOLD,
                      minimum=ZONE_CALIBRATION_MIN_SIZE):
    """单个作业区的选曲判定，规则与业务说明逐条对应。"""
    calibration_confirmed = confirmed_points(calibration_rows)
    replay_confirmed = confirmed_points(replay_rows)
    verification = prepare_verification(calibration_confirmed)
    positives = verification.positives
    eligible = (len(calibration_confirmed) >= minimum
                and verification.method != 'sparse-risk'
                and positives is not None and 0 < positives < verification.size)

    global_eval = (evaluate_curve_on_batch(global_curve, replay_confirmed, threshold)
                   if replay_confirmed else {'mse': None, 'misses': None})
    global_mse = global_eval['mse']
    global_misses = global_eval['misses'] if replay_confirmed else None

    if not eligible:
        reasons = ('ZONE_CALIBRATION_SPARSE',)
        if len(calibration_confirmed) < minimum:
            reasons = ('INSUFFICIENT_ZONE_ORDERS',)
        elif positives in (0, verification.size):
            reasons = ('ZONE_CLASS_MISSING',)
        return CurveDecision(cohort=cohort, chosen='global', adopted=False, curve=global_curve,
                             calibration_size=verification.size, positives=positives,
                             replay_size=len(replay_confirmed), threshold=threshold,
                             global_mse=global_mse, zone_mse=None,
                             global_misses=global_misses, zone_misses=None,
                             zone_curve=verification, reasons=reasons)

    zone_eval = evaluate_curve_on_batch(verification, replay_confirmed, threshold)
    zone_mse, zone_misses = zone_eval['mse'], zone_eval['misses']

    if not replay_confirmed or global_mse is None or zone_mse is None:
        adopted, reasons = False, ('NO_CONFIRMED_ZONE_REPLAY',)
    elif not zone_mse < global_mse:
        adopted, reasons = False, ('ZONE_MSE_NOT_LOWER',)
    elif zone_misses > global_misses:
        adopted, reasons = False, ('ZONE_EXTRA_MISSES',)
    else:
        adopted, reasons = True, ('ZONE_CURVE_ADOPTED',)

    return CurveDecision(cohort=cohort,
                         chosen='zone' if adopted else 'global',
                         adopted=adopted,
                         curve=verification if adopted else global_curve,
                         calibration_size=verification.size,
                         positives=positives,
                         replay_size=len(replay_confirmed),
                         threshold=threshold,
                         global_mse=global_mse, zone_mse=zone_mse,
                         global_misses=global_misses, zone_misses=zone_misses,
                         zone_curve=verification, reasons=reasons)


def select_zone_curves(calibration, replay=None, *, live=None, global_curve=None,
                       threshold=RISK_PROBABILITY_THRESHOLD,
                       minimum=ZONE_CALIBRATION_MIN_SIZE):
    """按作业区用同一批已确认回放单决定当班校准曲线。

    ``calibration`` / ``replay`` 可为带 ``cohort`` 属性的 Prediction 可迭代对象，
    也可为 ``{作业区: [Prediction, ...]}`` 映射。只传一个 Mapping 且带
    ``calibration`` / ``replay`` 两键时，也可一次传入。``live`` 仅用于让只有当班
    单据的作业区也出现在选曲结论中（必然回落全场曲线）。未提供 ``global_curve``
    时用全部校准单拟合全场曲线。返回 :class:`CurveSelection`。
    """
    if replay is None and isinstance(calibration, Mapping) \
            and 'calibration' in calibration and 'replay' in calibration:
        replay = calibration['replay']
        calibration = calibration['calibration']
    if replay is None:
        replay = ()
    cal_groups = _cohort_mapping(calibration)
    rep_groups = _cohort_mapping(replay)
    live_groups = _cohort_mapping(live) if live is not None else {}

    if global_curve is None:
        all_calibration = [point for rows in cal_groups.values() for point in rows]
        global_curve = prepare_verification(confirmed_points(all_calibration))

    cohorts = sorted(set(cal_groups) | set(rep_groups) | set(live_groups),
                     key=lambda name: (name is None, str(name)))
    decisions = tuple(choose_zone_curve(cohort, cal_groups.get(cohort, ()),
                                        rep_groups.get(cohort, ()), global_curve,
                                        threshold=threshold, minimum=minimum)
                      for cohort in cohorts)
    return CurveSelection(global_curve=global_curve, decisions=decisions)


# 语义别名。
build_zone_selection = select_zone_curves
choose_zone_curves = select_zone_curves
select_zone_verification = select_zone_curves
choose_zone_verification = select_zone_curves
resolve_zone_verification = select_zone_curves
zone_verification_selection = select_zone_curves
verification_for_zones = select_zone_curves
zone_curve_decisions = select_zone_curves
replay_curve_selection = select_zone_curves
replay_curve_choices = select_zone_curves
curve_choice_by_zone = select_zone_curves
select_calibration_curves = select_zone_curves
choose_calibration_curve = select_zone_curves
resolve_zone_curves = select_zone_curves
replay_zone_choices = select_zone_curves
replay_zone_curves = select_zone_curves
evaluate_zone_curves = select_zone_curves
assess_zone_curves = select_zone_curves
zone_calibration_curves = select_zone_curves
curve_selection_for_zones = select_zone_curves
calibration_for_shift = select_zone_curves
shift_calibration = select_zone_curves


def zone_curves(calibration, replay=None, **options):
    """直接返回 ``{作业区: 当班曲线 Verification}`` 的便捷封装。"""
    selection = select_zone_curves(calibration, replay, **options)
    return zone_curve_map(selection)


def curve_choices(calibration, replay=None, **options):
    """返回 ``{作业区: CurveDecision}`` 的便捷封装。"""
    return select_zone_curves(calibration, replay, **options).as_dict()


def zone_replay(calibration_or_selection, replay=None, threshold=RISK_PROBABILITY_THRESHOLD,
                **options):
    """分区回放选曲证据行（dict 列表）。

    可直接传 :class:`CurveSelection`，也可传校准/回放预测由本函数选曲。
    若第二个位置参数是数值，则按“已校验评估序列 + 门槛”的调用习惯处理，
    直接返回各作业区在该门槛下的漏查/命中证据。
    """
    if isinstance(calibration_or_selection, CurveSelection):
        return calibration_or_selection.evidence()
    if isinstance(replay, (int, float)) and not isinstance(replay, bool):
        threshold = float(replay)
        return zone_boundary_diagnostics(calibration_or_selection, threshold)
    return select_zone_curves(calibration_or_selection, replay,
                              threshold=threshold, **options).evidence()


cohort_replay = zone_replay
zone_replay_evidence = zone_replay
replay_by_zone = zone_replay


def zone_boundary_diagnostics(checked, threshold=RISK_PROBABILITY_THRESHOLD):
    """按作业区汇总已确认回放单在原门槛下的实绩/估计超线与漏查。"""
    groups = defaultdict(list)
    for row in checked:
        cohort, outcome, observed = _point_fields(row)
        if outcome is None or not observed or outcome not in (0, 1):
            continue
        estimate = getattr(row, 'estimate', None)
        if estimate is None:
            estimate = getattr(row, 'score', None)
        groups[cohort].append((estimate, outcome))
    statements = []
    for cohort in sorted(groups, key=lambda name: (name is None, str(name))):
        batch = groups[cohort]
        actual = sum(outcome == 1 for _, outcome in batch)
        over = sum(probability >= threshold for probability, _ in batch)
        hit = sum(probability >= threshold and outcome == 1 for probability, outcome in batch)
        statements.append({'作业区': cohort, '实绩数': len(batch), '实绩超线': actual,
                           '估计超线': over, '命中': hit, '漏查': actual-hit,
                           '额外复测': over-hit,
                           '已确认异常覆盖率': hit/actual if actual else None})
    return statements


def prepare_zone_verifications(calibration, *, minimum=ZONE_CALIBRATION_MIN_SIZE):
    """拟合每个作业区自己的校准曲线；不满足八单/两类实绩的区返回 sparse-risk。"""
    groups = _cohort_mapping(calibration)
    result = {}
    for cohort, rows in sorted(groups.items(), key=lambda item: (item[0] is None, item[0])):
        confirmed = confirmed_points(rows)
        verification = prepare_verification(confirmed)
        if len(confirmed) < minimum or verification.method == 'sparse-risk':
            result[cohort] = verification
        else:
            result[cohort] = verification
    return result


zone_verifications = prepare_zone_verifications
prepare_cohort_verifications = prepare_zone_verifications
cohort_verifications = prepare_zone_verifications
fit_zone_curves = prepare_zone_verifications
build_zone_curves = prepare_zone_verifications
fit_cohort_curves = prepare_zone_verifications
cohort_curves = prepare_zone_verifications
zone_calibration = prepare_zone_verifications
prepare_zone_calibration = prepare_zone_verifications


def zone_curve_map(selection):
    """返回 ``{作业区: 当班使用的 Verification}``，便于直接喂给 check_point。"""
    if isinstance(selection, CurveSelection):
        return {decision.cohort: decision.curve for decision in selection.decisions}
    if isinstance(selection, Mapping):
        return dict(selection)
    return {decision.cohort: decision.curve for decision in selection}


def validate_zone_predictions(scored, selection=None, global_curve=None):
    """当班/回放推断按作业区取已选定曲线；未知作业区与缺省选择都走全场曲线。"""
    if isinstance(selection, Verification):
        global_curve = selection
        selection = None
    if global_curve is None and isinstance(selection, CurveSelection):
        global_curve = selection.global_curve
    mapping = selection if isinstance(selection, Mapping) else None
    if global_curve is None and mapping is not None:
        global_curve = (mapping.get('__global__') or mapping.get('global')
                        or mapping.get('*') or mapping.get(None))
    if global_curve is None:
        global_curve = prepare_verification(())

    def curve_for(cohort):
        if selection is None:
            return global_curve
        if isinstance(selection, CurveSelection) or hasattr(selection, 'curve_for'):
            return selection.curve_for(cohort)
        if mapping is not None:
            return mapping.get(cohort) or global_curve
        return global_curve

    assessed = []
    for point in scored:
        assessed.append(check_point(point, curve_for(point.cohort)))
    return tuple(assessed)


validate_predictions_for_zones = validate_zone_predictions
calibrate_by_zone = validate_zone_predictions


def validation_curve_for(anchor, cohort=None):
    """让 validate_predictions 风格的调用也能解析分区选择。"""
    if isinstance(anchor, CurveSelection):
        return anchor.curve_for(cohort)
    return anchor



def reliability_rows(cases):
    consensus = [(0.,0,0) for _ in range(4)]
    boundaries = (.15,.4,.68)
    for forecast,observed in cases:
        i = bisect_right(boundaries,forecast)
        sum_forecast, total_positive, size = consensus[i]
        consensus[i] = sum_forecast+forecast,total_positive+observed,size+1
    return tuple(CalibrationRow(i,est/num if num else None,seen/num if num else None,num)
                 for i,(est,seen,num) in enumerate(consensus))


def performance(assessments):
    history = [(check.estimate,check.raw.outcome) for check in assessments if check.raw.observed and check.raw.outcome is not None]
    n = len(history)
    if not n:
        return ModelReport('NO_MATURE_RESULT',0,None,None,(),None)
    deviations = tuple(abs(estimated-confirmed) for estimated,confirmed in history)
    count = sum(outcome==1 for _,outcome in history)
    status = 'READY' if count else 'NO_POSITIVES'
    loss = fsum(stable_loss(*record) for record in history)
    return ModelReport(status,n,fsum(deviations)/n,loss/n,reliability_rows(history),count)


def calibration_evidence(report):
    segments = ('0–15%','15–40%','40–68%','68–100%')
    cards = [{'核验':report.status,'确认单量':report.count,'异常单量':report.auxiliary,
              '平均绝对残差':report.mae,'反常概率损失':report.error}]
    for span, group in zip(segments,report.buckets):
        cards.append({'异常概率区间':span,'样本数':group.count,'预测异常率':group.predicted,'实证异常率':group.observed})
    return cards


def sector_replay(checked, line):
    return replay_slices(checked,line)


def boundary_diagnostics(checks, threshold):
    joined = [row for row in checks if row.raw.observed and row.raw.outcome is not None]
    hit = sum(row.estimate>=threshold and row.raw.outcome==1 for row in joined)
    actual = sum(row.raw.outcome==1 for row in joined)
    forecast = sum(row.estimate>=threshold for row in joined)
    return {'临界判断':'风阻异常','实绩超线':actual,'估计超线':forecast,'额外复测':forecast-hit,'漏查':actual-hit,
            '优先队列命中率':hit/forecast if forecast else None,'已确认异常覆盖率':hit/actual if actual else None}
