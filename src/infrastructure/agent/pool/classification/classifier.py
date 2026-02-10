"""
项目分级器.

基于项目指标自动进行分级。
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional

from ..config import ClassificationConfig
from ..types import ProjectMetrics, ProjectTier, TierMigration

logger = logging.getLogger(__name__)


@dataclass
class ClassificationResult:
    """分级结果."""

    project_id: str
    tenant_id: str
    tier: ProjectTier
    score: int
    breakdown: Dict[str, int]  # 各维度得分
    reason: str


class ProjectClassifier:
    """项目分级器.

    基于以下维度对项目进行分级:
    - 请求频率 (40%)
    - 付费等级 (30%)
    - SLA要求 (20%)
    - 并发要求 (10%)
    """

    def __init__(self, config: Optional[ClassificationConfig] = None):
        """初始化分级器.

        Args:
            config: 分级配置
        """
        self.config = config or ClassificationConfig()

        logger.info(
            f"[ProjectClassifier] Initialized: "
            f"hot_threshold={self.config.hot_score_threshold}, "
            f"warm_threshold={self.config.warm_score_threshold}"
        )

    def classify(self, metrics: ProjectMetrics) -> ClassificationResult:
        """对项目进行分级.

        Args:
            metrics: 项目指标

        Returns:
            分级结果
        """
        breakdown = {}
        reasons = []

        # 请求频率 (权重 40%)
        request_score = self._score_requests(metrics.daily_requests)
        breakdown["requests"] = request_score
        if metrics.daily_requests > self.config.hot_request_threshold:
            reasons.append(f"高请求量({metrics.daily_requests}/天)")

        # 付费等级 (权重 30%)
        subscription_score = self._score_subscription(metrics.subscription_tier)
        breakdown["subscription"] = subscription_score
        if metrics.subscription_tier == "enterprise":
            reasons.append("企业版订阅")

        # SLA要求 (权重 20%)
        sla_score = self._score_sla(metrics.sla_requirement)
        breakdown["sla"] = sla_score
        if metrics.sla_requirement >= self.config.high_sla_threshold:
            reasons.append(f"高SLA要求({metrics.sla_requirement * 100:.1f}%)")

        # 并发要求 (权重 10%)
        concurrent_score = self._score_concurrent(metrics.max_concurrent)
        breakdown["concurrent"] = concurrent_score
        if metrics.max_concurrent > self.config.high_concurrent_threshold:
            reasons.append(f"高并发({metrics.max_concurrent})")

        # 计算总分
        total_score = (
            int(request_score * self.config.request_weight)
            + int(subscription_score * self.config.subscription_weight)
            + int(sla_score * self.config.sla_weight)
            + int(concurrent_score * self.config.concurrent_weight)
        )

        # 确定分级
        if total_score >= self.config.hot_score_threshold:
            tier = ProjectTier.HOT
        elif total_score >= self.config.warm_score_threshold:
            tier = ProjectTier.WARM
        else:
            tier = ProjectTier.COLD

        reason = "; ".join(reasons) if reasons else "默认分级"

        result = ClassificationResult(
            project_id=metrics.project_id,
            tenant_id=metrics.tenant_id,
            tier=tier,
            score=total_score,
            breakdown=breakdown,
            reason=reason,
        )

        logger.debug(
            f"[ProjectClassifier] Classified: "
            f"project={metrics.project_id}, "
            f"tier={tier.value}, score={total_score}"
        )

        return result

    def _score_requests(self, daily_requests: int) -> int:
        """计算请求频率得分."""
        if daily_requests > self.config.hot_request_threshold:
            return 100
        elif daily_requests > self.config.warm_request_threshold:
            return 60
        else:
            return 25

    def _score_subscription(self, tier: str) -> int:
        """计算付费等级得分."""
        scores = {
            "enterprise": self.config.enterprise_score,
            "professional": self.config.professional_score,
            "basic": self.config.basic_score,
            "free": self.config.free_score,
        }
        return scores.get(tier.lower(), self.config.free_score)

    def _score_sla(self, sla: float) -> int:
        """计算SLA要求得分."""
        if sla >= self.config.high_sla_threshold:
            return 100
        elif sla >= self.config.medium_sla_threshold:
            return 70
        else:
            return 30

    def _score_concurrent(self, max_concurrent: int) -> int:
        """计算并发要求得分."""
        if max_concurrent > self.config.high_concurrent_threshold:
            return 100
        elif max_concurrent > self.config.medium_concurrent_threshold:
            return 60
        else:
            return 30

    def should_upgrade(
        self,
        current_tier: ProjectTier,
        metrics: ProjectMetrics,
    ) -> Optional[ProjectTier]:
        """检查是否应该升级.

        Args:
            current_tier: 当前分级
            metrics: 项目指标

        Returns:
            目标分级或None (不需要升级)
        """
        result = self.classify(metrics)

        # 只升不降
        tier_order = {
            ProjectTier.COLD: 0,
            ProjectTier.WARM: 1,
            ProjectTier.HOT: 2,
        }

        if tier_order[result.tier] > tier_order[current_tier]:
            return result.tier

        return None

    def should_downgrade(
        self,
        current_tier: ProjectTier,
        metrics: ProjectMetrics,
        consecutive_days: int = 7,
    ) -> Optional[ProjectTier]:
        """检查是否应该降级.

        降级需要更保守的策略，通常需要连续多天指标下降。

        Args:
            current_tier: 当前分级
            metrics: 项目指标
            consecutive_days: 连续天数 (用于决策)

        Returns:
            目标分级或None (不需要降级)
        """
        result = self.classify(metrics)

        tier_order = {
            ProjectTier.COLD: 0,
            ProjectTier.WARM: 1,
            ProjectTier.HOT: 2,
        }

        # 只有当新分级低于当前且连续多天才降级
        if tier_order[result.tier] < tier_order[current_tier]:
            # 这里简化处理，实际应该检查历史记录
            return result.tier

        return None

    def create_migration(
        self,
        project_id: str,
        tenant_id: str,
        from_tier: ProjectTier,
        to_tier: ProjectTier,
        reason: str,
    ) -> TierMigration:
        """创建分级迁移记录.

        Args:
            project_id: 项目ID
            tenant_id: 租户ID
            from_tier: 原分级
            to_tier: 目标分级
            reason: 迁移原因

        Returns:
            迁移记录
        """
        return TierMigration(
            project_id=project_id,
            tenant_id=tenant_id,
            from_tier=from_tier,
            to_tier=to_tier,
            reason=reason,
            scheduled_at=datetime.now(timezone.utc),
            status="pending",
        )
