import json
from pathlib import Path

kg_path = Path(r"d:\openGuiclaw\data\memory\knowledge_graph.jsonl")
if not kg_path.exists():
    print("Graph file not found.")
    exit(0)

bad_subjects = {"AI", "Agent", "agent-browser", "msedge", "Edge 浏览器", "browser_open", "start msedge", "Win+R", "记忆库", "系统", "小助"}
bad_relations_exact = {
    "编辑", "配置", "运行", "调试", "观看", "访问", "查阅", "记录", 
    "访问 UP 主", "保存文件", "打开网页", "查询天气", "发送消息", 
    "指令", "指令打开", "发送指令", "查询", "询问", "要求使用"
}
bad_relations_substring = {"访问", "打开", "尝试", "成功", "执行", "加载", "启动", "调用", "发送", "维护组件", "使用命令"}

new_triples = []
with open(kg_path, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except:
            continue
        
        s = item.get("subject", "")
        r = item.get("relation", "")
        
        if s in bad_subjects:
            continue
        
        if r in bad_relations_exact:
            continue
            
        drop = False
        for sub in bad_relations_substring:
            if sub in r:
                drop = True
                break
        if drop:
            continue
            
        new_triples.append(item)

print(f"Cleaned up {kg_path}. Kept {len(new_triples)} records.")

with open(kg_path, "w", encoding="utf-8") as f:
    for item in new_triples:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")
