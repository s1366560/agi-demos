/**
 * Execution Summary
 *
 * Displays a summary of the current execution including work plan and tool executions.
 */

import { WorkPlanCard } from "./WorkPlanCard";
import { ToolExecutionCard } from "./ToolExecutionCard";

export function ExecutionSummary() {
  // Only show during streaming or when there's data
  // The child components will handle their own visibility

  return (
    <div className="mb-4">
      <WorkPlanCard variant="full" />
      <ToolExecutionCard variant="card" />
    </div>
  );
}
