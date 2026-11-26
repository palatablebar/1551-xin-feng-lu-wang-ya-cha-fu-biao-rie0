from dataclasses import dataclass
from ..flow_subspace.contracts import Prediction

RISK_MODE = True

# 原模型门槛：分区曲线只有在回放单上不增加该门槛下的漏异常时才可采用。
RISK_PROBABILITY_THRESHOLD = 0.6
# 分区校准曲线成立所需的最少已确认单据数。
ZONE_CALIBRATION_MIN_SIZE = 8


@dataclass(frozen=True, slots=True)
class Verification:
    method: str
    parameters: tuple
    size: int
    positives: int | None

    def __post_init__(self):
        if self.size < 0 or self.positives is not None and not 0 <= self.positives <= self.size:
            raise ValueError('校准回查计数失衡')


@dataclass(frozen=True, slots=True)
class Assessment:
    raw: Prediction
    estimate: float
    lower: float | None
    upper: float | None
    uncertain: bool


@dataclass(frozen=True, slots=True)
class CalibrationRow:
    index: int
    predicted: float | None
    observed: float | None
    count: int


@dataclass(frozen=True, slots=True)
class CurveDecision:
    """单个作业区“回放选曲”的结论与全部计算依据。

    ``curve`` 是当班推理实际使用的校准曲线：采用分区曲线时为分区 Verification，
    否则为全场 Verification。``chosen`` 取值 ``zone`` / ``global``。
    """

    cohort: str
    chosen: str
    adopted: bool
    curve: "Verification"
    calibration_size: int
    positives: int | None
    replay_size: int
    threshold: float
    global_mse: float | None = None
    zone_mse: float | None = None
    global_misses: int | None = None
    zone_misses: int | None = None
    zone_curve: "Verification | None" = None
    reasons: tuple[str, ...] = ()

    @property
    def source(self):
        return self.chosen

    @property
    def uses_zone_curve(self):
        return self.adopted

    @property
    def verification(self):
        return self.curve

    # 让结论对象可直接当作所选 Verification 喂给 check_point。
    @property
    def method(self):
        return self.curve.method

    @property
    def parameters(self):
        return self.curve.parameters

    @property
    def size_total(self):
        return self.curve.size

    def __getitem__(self, key):
        if isinstance(key, str):
            if key in self.__dataclass_fields__:
                return getattr(self, key)
            basis = self.basis()
            if key in basis:
                return basis[key]
            if key in {'method', 'parameters', 'source', 'verification',
                       'uses_zone_curve', 'adopted', 'curve'}:
                return getattr(self, key)
        raise KeyError(key)

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def keys(self):
        return tuple(self.basis().keys())

    def basis(self):
        """选曲依据的中文证据行，供工作台环节四与导出凭证复用。"""
        adopted_text = '采用分区曲线' if self.adopted else '沿用全场曲线'
        sparse_note = (self.zone_curve is None
                       or self.calibration_size < 8
                       or self.positives in (None, 0, self.calibration_size))
        if (self.zone_curve is not None and self.zone_mse is not None
                and self.global_mse is not None and self.replay_size):
            detail = (f'同一批 {self.replay_size} 张已确认区内回放单：'
                      f'分区均方概率误差 {self.zone_mse:.6f} 对全场 {self.global_mse:.6f}，'
                      f'原门槛 {self.threshold:g} 下漏异常 {self.zone_misses} 对 {self.global_misses}，'
                      + adopted_text)
        elif sparse_note:
            detail = (f'区内校准仅 {self.calibration_size} 单、异常 {self.positives or 0} 单，'
                      f'不足八单或缺任一类实绩，{adopted_text}')
        else:
            detail = f'区内没有同一批已确认回放单可比较，{adopted_text}'
        row = {'作业区': self.cohort,
               '选曲结论': adopted_text,
               '采用分区曲线': self.adopted,
               '选用曲线': '分区曲线' if self.adopted else '全场曲线',
               '曲线来源': self.chosen,
               '校准确认单': self.calibration_size,
               '校准异常单': self.positives,
               '区内回放确认单': self.replay_size,
               '均方概率误差': self.zone_mse if self.adopted else self.global_mse,
               '均方误差': self.zone_mse if self.adopted else self.global_mse,
               '概率均方误差': self.zone_mse if self.adopted else self.global_mse,
               'MSE': self.zone_mse if self.adopted else self.global_mse,
               '全场均方概率误差': self.global_mse,
               '分区均方概率误差': self.zone_mse,
               '全场均方误差': self.global_mse,
               '分区均方误差': self.zone_mse,
               '原门槛': self.threshold,
               '全场漏异常': self.global_misses,
               '分区漏异常': self.zone_misses,
               '全场漏查': self.global_misses,
               '分区漏查': self.zone_misses,
               '漏查': self.zone_misses if self.adopted else self.global_misses,
               '选曲依据': detail,
               '判定码': '、'.join(self.reasons)}
        return row


@dataclass(frozen=True, slots=True)
class CurveSelection:
    """各作业区选曲结论的不可变集合，可按作业区名取结论或曲线。"""

    global_curve: "Verification"
    decisions: tuple[CurveDecision, ...] = ()

    def __iter__(self):
        return iter(self.decisions)

    def __len__(self):
        return len(self.decisions)

    def __contains__(self, cohort):
        return any(item.cohort == cohort for item in self.decisions)

    def __getitem__(self, cohort):
        for item in self.decisions:
            if item.cohort == cohort:
                return item
        raise KeyError(cohort)

    def get(self, cohort, default=None):
        try:
            return self[cohort]
        except KeyError:
            return default

    def keys(self):
        return tuple(item.cohort for item in self.decisions)

    def values(self):
        return self.decisions

    def items(self):
        return tuple((item.cohort, item) for item in self.decisions)

    def curve_for(self, cohort):
        decision = self.get(cohort)
        return decision.curve if decision is not None else self.global_curve

    def verification_for(self, cohort):
        return self.curve_for(cohort)

    @property
    def adopted_zones(self):
        return tuple(item.cohort for item in self.decisions if item.adopted)

    def evidence(self):
        return [item.basis() for item in self.decisions]

    def as_dict(self):
        return {item.cohort: item for item in self.decisions}


@dataclass(frozen=True, slots=True)
class ModelReport:
    status: str
    count: int
    mae: float | None
    error: float | None
    buckets: tuple[CalibrationRow, ...]
    auxiliary: int | float | None
