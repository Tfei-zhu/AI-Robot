"""上下文数据契约，摘要中的条目必须能追溯到原始轮次。"""
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContextBudgetExceeded(ValueError):
    code="context_budget_exceeded"


class SummaryItem(BaseModel):
    model_config=ConfigDict(extra="forbid")
    text: str = Field(min_length=1,max_length=2000)
    source_turns: list[int] = Field(min_length=1)
    active: bool = True
    evidence_refs: list[str] = Field(default_factory=list)


class CorrectionItem(SummaryItem):
    # 明确关联被替代的原约束，不能凭一段自由文本推断撤销关系。
    supersedes: list[str] = Field(default_factory=list)


class SessionSummary(BaseModel):
    model_config=ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    covered_until_turn: int = Field(ge=1)
    goal: list[SummaryItem] = Field(default_factory=list)
    constraints: list[SummaryItem] = Field(default_factory=list)
    corrections: list[CorrectionItem] = Field(default_factory=list)
    confirmed_facts: list[SummaryItem] = Field(default_factory=list)
    decisions: list[SummaryItem] = Field(default_factory=list)
    completed: list[SummaryItem] = Field(default_factory=list)
    pending: list[SummaryItem] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def collect_evidence_refs(self):
        # 条目级引用汇总到根节点，统一执行归属校验、补读和长度预算。
        refs=list(self.evidence_refs)
        for key in ("goal","constraints","corrections","confirmed_facts","decisions","completed","pending"):
            for item in getattr(self,key):refs.extend(item.evidence_refs)
        self.evidence_refs=list(dict.fromkeys(refs))
        return self


def scope(session):
    # 内部会话键由认证层提供，模型不允许选择 owner 或 session。
    return session.split(":",1)[0],session
