import argparse
import sys
import io

# 强制兼容 UTF-8 输出，避免 Windows 控制台编码报错
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from core.agent import Agent

def main():
    parser = argparse.ArgumentParser(description="手动强制重新触发指定日期的自我进化流程 (Chat Summary -> Diary -> Memory -> KG -> Persona)。")
    parser.add_argument("date", help="指定日期格式，例如: 2026-02-19")
    args = parser.parse_args()
    
    date_str = args.date

    print(f"[System] 初始化 Agent，准备对 {date_str} 进行自我进化...\n")
    agent = Agent(auto_evolve=False)
    
    print("-" * 50)
    print("【步骤 1】汇总对话记录")
    agent._summarize_day_conversations(date_str)
    print("-" * 50)

    print("【步骤 2】从完整日志 (视觉+聊天) 提取 日记、记忆 与 知识图谱")
    new_mems = agent.evolution.evolve_from_journal(date_str)
    if new_mems:
        print(f"\n✨ 共习得 {len(new_mems)} 条核心记忆：")
        for m in new_mems:
            print(f"  - {m}")
    else:
        print("\n未提取到新的强信号核心记忆。")
    print("-" * 50)

    print("【步骤 3】尝试交互习惯进化 (Interaction Habits)")
    updated = agent.evolution.evolve_persona()
    if updated:
        print("💡 交互习惯已发生微调！")
    else:
        print("无需微调交互习惯。")
    print("-" * 50)

    print(f"\n✅ {date_str} 的手工进化流程执行完毕。")
    print(f"💡 (提示：如果修改后的结果依然包含旧记忆，请手动进入 data/memory.jsonl 删掉无用条目即可)")

    # 强制退出，避免 agent() 初始化的守护线程/后台线程阻塞进程
    import os
    os._exit(0)

if __name__ == "__main__":
    main()
