from pathlib import Path
from core.identity_manager import IdentityManager

manager = IdentityManager("data")
prompt = manager.build_prompt()

print("--- PROMPT START ---\n")
print(prompt[:500]) # only print first 500 chars to check if AGENT.md is at the top
print("\n--- PROMPT END ---")
