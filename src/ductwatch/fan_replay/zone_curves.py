"""作业区分区校准曲线与回放选曲（规范实现位于 :mod:`ductwatch.fan_replay.service`）。"""

from .contracts import (CurveDecision, CurveSelection,
                        RISK_PROBABILITY_THRESHOLD, ZONE_CALIBRATION_MIN_SIZE)
from .service import (
    select_zone_curves, choose_zone_curves, build_zone_selection,
    zone_curve_decisions, replay_curve_selection, zone_curves, curve_choices,
    prepare_zone_verifications, zone_verifications,
    prepare_cohort_verifications, cohort_verifications,
    validate_zone_predictions, validate_predictions_for_zones,
    zone_curve_map, choose_zone_curve, evaluate_curve_on_batch, compare_curves,
    confirmed_points, confirmed_cases, group_by_cohort,
    mean_squared_probability_error, mean_squared_error, brier_score,
    probability_mse, missed_anomalies_at_threshold, missed_anomaly_count,
    missed_anomalies,
)

__all__ = (
    'CurveDecision', 'CurveSelection', 'RISK_PROBABILITY_THRESHOLD',
    'ZONE_CALIBRATION_MIN_SIZE', 'select_zone_curves', 'choose_zone_curves',
    'build_zone_selection', 'zone_curve_decisions', 'replay_curve_selection',
    'zone_curves', 'curve_choices', 'prepare_zone_verifications',
    'zone_verifications', 'prepare_cohort_verifications',
    'cohort_verifications', 'validate_zone_predictions',
    'validate_predictions_for_zones', 'zone_curve_map', 'choose_zone_curve',
    'evaluate_curve_on_batch', 'confirmed_points', 'confirmed_cases',
    'group_by_cohort', 'mean_squared_probability_error', 'mean_squared_error',
    'brier_score', 'probability_mse', 'missed_anomalies_at_threshold',
    'missed_anomaly_count', 'missed_anomalies',
)
