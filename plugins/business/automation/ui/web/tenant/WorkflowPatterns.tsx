import { useParams } from "react-router-dom";
import { patternService, PatternServiceError } from "@/services/patternService";
import {
  WorkflowPatternsView,
  type PatternClient,
} from "./WorkflowPatternsView";

const client: PatternClient = {
  listPatterns: (tenant) => patternService.listPatterns(tenant),
  deletePattern: (id, tenant) => patternService.deletePattern(id, tenant),
  errorMessage: (error) =>
    error instanceof PatternServiceError ? error.message : null,
};
export function WorkflowPatterns() {
  const { tenantId } = useParams<{ tenantId: string }>();
  return <WorkflowPatternsView tenantId={tenantId} client={client} canDelete />;
}

export default WorkflowPatterns;
