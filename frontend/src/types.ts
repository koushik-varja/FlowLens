export type Scalar = string | number | boolean | null;
export type JsonObject = Record<string, unknown>;

export interface GraphActivity {
  activity: string;
  frequency: number;
  case_percentage: number;
  resource_count: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  frequency: number;
  case_percentage: number;
  median_inter_event_delay_hours: number;
  p95_inter_event_delay_hours: number | null;
}

export interface ProcessGraph {
  activities: GraphActivity[];
  edges: GraphEdge[];
  case_count: number;
  event_count: number;
  start_activities: Record<string, number>;
  end_activities: Record<string, number>;
  terminology_note: string;
}

export interface Variant {
  path: string[];
  case_count: number;
  percentage: number;
  median_duration_hours: number;
  sla_breach_rate: number;
  avg_cost: number | null;
}

export type ConditionField = 'priority' | 'value' | 'customer_type' | 'region' | 'department' | 'channel';
export type ConditionOperator = 'eq' | 'neq' | 'lt' | 'lte' | 'gt' | 'gte' | 'in';
export interface Condition { field: ConditionField; op: ConditionOperator; value: string | number | string[] }

export interface ActivitySpeedupAction { type: 'activity_speedup'; activity: string; reduction_fraction: number }
export interface RemoveActivityAction { type: 'remove_activity'; activity: string }
export interface AddResourceCapacityAction { type: 'add_resource_capacity'; activity: string; additional_capacity: number; service_fraction: number }
export interface AutomateEligibleCasesAction {
  type: 'automate_eligible_cases'; activity: string; conditions: Condition[]; reduction_fraction: number; processing_effort_saved_minutes?: number | null
}
export interface ParallelizeActivitiesAction { type: 'parallelize_activities'; first_activity: string; second_activity: string }
export interface RouteCasesAction { type: 'route_cases'; conditions: Condition[]; from_activity: string; to_activity: string }
export interface ChangePriorityRoutingAction { type: 'change_priority_routing'; priority: string; activity: string; reduction_fraction: number }
export interface ChangeSlaAction { type: 'change_sla'; hours: number }

export type TransformationAction =
  | ActivitySpeedupAction
  | RemoveActivityAction
  | AddResourceCapacityAction
  | AutomateEligibleCasesAction
  | ParallelizeActivitiesAction
  | RouteCasesAction
  | ChangePriorityRoutingAction
  | ChangeSlaAction;

export interface Scenario {
  name: string;
  actions: TransformationAction[];
  runs: number;
  sla_hours: number;
  seed: number;
  cohort_size?: number | null;
}

export interface SimulationMetrics {
  mean_cycle_hours: number;
  median_cycle_hours: number;
  p90_cycle_hours: number;
  p95_cycle_hours: number;
  sla_compliance: number;
  simulated_throughput_cases_per_30d: number;
  estimated_process_cost: number;
  modeled_queue_delay_hours?: number;
  resource_utilization?: number;
}

export interface UncertaintyBand { median: number; p10: number; p90: number }
export interface BaselineFidelity {
  status: 'HIGH' | 'MEDIUM' | 'LOW';
  warning: string | null;
  observed: Record<string, number>;
  simulated_baseline: Record<string, number>;
}
export interface ThroughputMethodology {
  metric: string;
  arrival_model: string;
  historical_arrival_rate_cases_per_hour: number;
  historical_arrival_rate_cases_per_30d: number;
  arrival_observation_span_hours: number;
  simulation_horizon_hours: number;
  warmup_hours: number;
  paired_baseline_proposed_arrivals: boolean;
  independent_of_analysis_cohort_size: boolean;
}

export interface ScenarioResult {
  scenario: Scenario;
  baseline: SimulationMetrics;
  proposed: SimulationMetrics;
  simulated_impact: {
    median_cycle_reduction_pct: number;
    p95_cycle_delta_hours: number;
    sla_compliance_delta_pp: number;
    throughput_delta_cases_per_30d: number;
    [key: string]: number;
  };
  uncertainty: {
    cycle_time_reduction_pct: UncertaintyBand;
    median_cycle_delta_hours: UncertaintyBand;
    sla_compliance_delta_pp: UncertaintyBand;
  };
  baseline_fidelity: BaselineFidelity;
  throughput_methodology: ThroughputMethodology;
  resource_diagnostics: unknown[];
  disclaimer: string;
}

export interface SLAResult {
  rules: Array<{
    name: string;
    scope: string;
    assessed_cases: number;
    violation_count: number;
    compliance_rate: number;
    severity: string;
  }>;
}

export interface ActiveCasePrediction {
  case_id: string;
  current_activity: string;
  elapsed_hours: number;
  activities_completed: number;
  rework_count: number;
  priority: string | null;
  breach_probability: number;
  expected_remaining_hours: number;
  predicted_completion_time: string;
  risk_level: string;
  feature_timestamp: string;
  model_version: string;
}
export interface ActiveCaseResponse { cutoff: string; model_version: string; cases: ActiveCasePrediction[]; detail?: string }

export interface BusinessAssumptions {
  cases_per_month: number;
  labor_cost_per_hour: number;
  processing_effort_by_activity_minutes: Record<string, number>;
  sla_breach_cost: number;
  rework_cost: number;
  automation_cost_monthly: number;
  implementation_cost_monthly: number;
  value_of_faster_completion_per_hour: number;
  illustrative: boolean;
}

export interface BusinessImpact {
  estimated_monthly_value: number;
  categories: {
    time_to_completion_value: number;
    labor_effort_savings: number;
    sla_cost_avoidance: number;
    rework_savings: number;
    recurring_costs: number;
  };
  lead_time_hours_saved_per_case: number;
  assumption_label: string;
  disclaimer: string;
  assumptions: BusinessAssumptions;
}

export interface ModelMetrics {
  version: string;
  training_timestamp: string;
  training_cutoff?: string;
  metrics: { precision: number; recall: number; f1: number; roc_auc: number | null; pr_auc: number | null };
  remaining_metrics: { mae_hours: number; median_absolute_error_hours: number; rmse_hours: number };
  split: { train_cases: number; test_cases: number; training_cutoff?: string };
}

export type SimulationResult = ScenarioResult;
