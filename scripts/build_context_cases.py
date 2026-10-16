"""生成固定长对话脚本；答案只用于验收，不代替模型的中间回答。"""
import json
from pathlib import Path


def build_cases():
    rows=[]
    kinds=["early_constraint","correction","repeat_search","tail_evidence","topic_shift","new_query"]
    for i in range(30):
        n=[10,30,60][(i+i//6)%3];kind=kinds[i%6]
        holdout=i>=20
        version=["1.24.0","1.25.0","1.26.2","1.23.0"][i%4] if holdout else "1.26.2"
        code=f"HOLD-{i:02d}-Z" if holdout else f"CTX-{i:02d}"
        initial=(f"项目语言固定为 Go，工具链版本 {version}，外部依赖禁止（仅标准库），任务标识 {code}。以下穿插讨论不更改这些要求；最后按指定 JSON 字段回填。现在仅确认收到。" if holdout else
                 f"进行长对话工程任务。请记住本任务要求：语言 Go、版本 {version}、依赖仅标准库、任务编号 {code}。后面会插入其他话题，最终请按我的格式回答。现在只回复已记录。")
        turns=[initial];ordinary_turns=[]
        for t in range(1,n-1):
            if kind=="correction" and t==2:
                version="1.25.1" if holdout else "1.25.0"
                turns.append(f"纠正刚才的版本：改为 Go {version}，其他要求保持。请确认。")
            elif t in (3,6) and kind in ("repeat_search","tail_evidence","new_query"):
                query="context deadline" if not(kind=="new_query" and t==6) else "context cancellation 不使用 deadline"
                turns.append(f"请调用知识检索查询“{query}”，确认资料中的超时数值。回答简短。")
            else:
                # 明确总字符上限，避免模型按汉字/英文词数理解而评分按Unicode字符计数。
                turns.append(f"穿插话题 {t}：从 Go 命名/日志/测试中任选一项，给出一条建议。回复最多 30 个字符（英文、数字、标点均计数）。原工程约束继续有效。" if holdout else
                             f"插入第 {t} 轮讨论：命名、日志、测试任选一项，给一条 Go 建议。回复不超过 30 个字符（含英文、数字及标点）。此话题不修改原任务约束。")
                ordinary_turns.append(len(turns))
        turns.append("回到原工程任务。只输出一个 JSON 对象，字段 language、version、dependency、task_id，填写之前确认的有效要求，不要附加解释。")
        rows.append({"id":f"context-{i:02d}","split":"dev" if i<20 else "holdout","kind":kind,
                     "turns":turns,"expected":{"language":"Go","version":version,"dependency":"标准库","task_id":code},
                     "length":n,"knowledge_revision":1,"dataset_version":3,"ordinary_turns":ordinary_turns,
                     "ordinary_constraint":{"max_characters":30,"counting":"Unicode字符，含英文、数字、标点和内部空格；首尾空白不计"}})
    return rows


if __name__=="__main__":
    target=Path(__file__).resolve().parents[1]/"eval/context_cases.jsonl"
    target.write_text("\n".join(json.dumps(c,ensure_ascii=False) for c in build_cases())+"\n",encoding="utf-8")
    print("已生成 30 条固定脚本：20 开发、10 留出，10/30/60 轮")
