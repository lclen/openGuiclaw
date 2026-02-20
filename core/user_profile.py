"""
User Profile Manager

Manages a dedicated JSON file for storing structural information about the user.
This ensures highly concentrated, factual user traits (name, age, preferences, etc.)
are always present in the system prompt without cluttering episodic memory.
"""

import json
from pathlib import Path
from typing import Dict, Any

class UserProfileManager:
    def __init__(self, data_dir: str, profile_filename: str = "user_profile.json"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.profile_path = self.data_dir / profile_filename
        self.profile_data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        """Load user profile from JSON file and ensure schema."""
        default_schema = {
            "objective_memory": {},
            "subjective_memory": {}
        }
        
        if self.profile_path.exists():
            try:
                with open(self.profile_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    
                    # Migration from flat structure
                    if "objective_memory" not in data and "subjective_memory" not in data:
                        migrated_data = {"objective_memory": data, "subjective_memory": {}}
                        return migrated_data
                    
                    # Ensure both layers exist
                    if "objective_memory" not in data: data["objective_memory"] = {}
                    if "subjective_memory" not in data: data["subjective_memory"] = {}
                    
                    return data
            except Exception as e:
                print(f"[UserProfile] Failed to load {self.profile_path}: {e}")
                
        return default_schema

    def _save(self) -> None:
        """Save user profile to JSON file."""
        try:
            with open(self.profile_path, "w", encoding="utf-8") as f:
                json.dump(self.profile_data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"[UserProfile] Failed to save {self.profile_path}: {e}")

    def update_objective(self, key: str, value: str) -> None:
        """Update or add a specific user objective trait (facts)."""
        self.profile_data["objective_memory"][key] = value
        self._save()
        print(f"[UserProfile] 客观档案已更新: {key} -> {value}")

    def update_subjective(self, key: str, value: str) -> None:
        """Update or add a specific user subjective trait (rules, preferences)."""
        self.profile_data["subjective_memory"][key] = value
        self._save()
        print(f"[UserProfile] 主观偏好已更新: {key} -> {value}")

    def get_all(self) -> Dict[str, Any]:
        """Get all profile traits."""
        return self.profile_data

    def build_prompt(self) -> str:
        """Build the text block to be injected into the system prompt."""
        if not self.profile_data.get("objective_memory") and not self.profile_data.get("subjective_memory"):
            return ""
        
        lines = []
        
        obj_mem = self.profile_data.get("objective_memory", {})
        if obj_mem:
            lines.append("# 客观状态与身份 (Objective Memory)")
            for key, value in obj_mem.items():
                lines.append(f"- **{key}**: {value}")
            lines.append("")
                
        sub_mem = self.profile_data.get("subjective_memory", {})
        if sub_mem:
            lines.append("# 主观偏好与约束 (Subjective Memory) [核心指令，不可违背]")
            for key, value in sub_mem.items():
                lines.append(f"- **{key}**: {value}")
            lines.append("")
            
        return "\n".join(lines).strip()
