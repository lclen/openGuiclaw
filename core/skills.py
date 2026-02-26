"""
Skill Manager: Plugin-style tool registration and execution.

Any Python function decorated with @skill can be registered.
Skills return (str) results that are fed back to the LLM.
"""

from typing import Callable, Dict, Any, List, Optional
from dataclasses import dataclass, field


@dataclass
class SkillDefinition:
    """Metadata for a registered skill / tool."""
    name: str
    description: str
    parameters: Dict[str, Any]          # JSON Schema style
    handler: Callable
    enabled: bool = True
    category: str = "general"
    ui_config: Optional[List[Dict[str, Any]]] = field(default_factory=list)
    config_values: Dict[str, Any] = field(default_factory=dict)



class SkillManager:
    """
    Manages all registered skills.

    Usage:
        manager = SkillManager()

        @manager.skill(
            name="get_time",
            description="Returns the current date and time.",
            parameters={}
        )
        def get_time():
            import time
            return time.strftime("%Y-%m-%d %H:%M:%S")
    """

    def __init__(self, config_path: str = "data/skills.json"):
        self._registry: Dict[str, SkillDefinition] = {}
        self.config_path = config_path
        self._config_data: Dict[str, Any] = {}
        self._load_config()

    def _load_config(self) -> None:
        import os, json
        if not os.path.exists(self.config_path):
            self._config_data = {}
            return
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                self._config_data = json.load(f)
        except Exception as e:
            print(f"[SkillManager] Failed to load config: {e}")
            self._config_data = {}

    def _save_config(self) -> None:
        import os, json
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        data = {}
        for name, skill in self._registry.items():
            data[name] = {
                "enabled": skill.enabled,
                "config_values": skill.config_values
            }
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[SkillManager] Failed to save config: {e}")

    def register(self, skill: SkillDefinition) -> None:
        """Register a skill."""
        if skill.name in self._config_data:
            skill.enabled = self._config_data[skill.name].get("enabled", skill.enabled)
            skill.config_values = self._config_data[skill.name].get("config_values", skill.config_values)
        self._registry[skill.name] = skill

    def skill(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        category: str = "general",
        enabled: bool = True,
        ui_config: Optional[List[Dict[str, Any]]] = None,
    ):
        """Decorator to register a function as a skill."""
        def decorator(func: Callable) -> Callable:
            self.register(SkillDefinition(
                name=name,
                description=description,
                parameters=parameters,
                handler=func,
                enabled=enabled,
                category=category,
                ui_config=ui_config or [],
            ))
            return func
        return decorator

    def enable(self, name: str) -> None:
        if name in self._registry:
            self._registry[name].enabled = True
            self._save_config()

    def disable(self, name: str) -> None:
        if name in self._registry:
            self._registry[name].enabled = False
            self._save_config()

    def update_config(self, name: str, config: Dict[str, Any]) -> None:
        if name in self._registry:
            self._registry[name].config_values.update(config)
            self._save_config()

    def get(self, name: str) -> Optional[SkillDefinition]:
        return self._registry.get(name)

    def list_enabled(self) -> List[SkillDefinition]:
        return [s for s in self._registry.values() if s.enabled]

    async def execute(self, name: str, params: Dict[str, Any]) -> str:
        """Execute a skill by name with given parameters. Supports both sync and async handlers."""
        import asyncio
        skill = self._registry.get(name)
        if skill is None:
            return f"[SkillManager] Unknown skill: '{name}'"
        if not skill.enabled:
            return f"[SkillManager] Skill '{name}' is disabled."
        try:
            if asyncio.iscoroutinefunction(skill.handler):
                result = await skill.handler(**params)
            else:
                result = skill.handler(**params)
                if asyncio.iscoroutine(result):
                    result = await result
            return str(result) if result is not None else "Done."
        except Exception as e:
            return f"[SkillManager] Error executing '{name}': {e}"

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Return tool definitions in OpenAI function-calling format."""
        tools = []
        for skill in self.list_enabled():
            tools.append({
                "type": "function",
                "function": {
                    "name": skill.name,
                    "description": skill.description,
                    "parameters": {
                        "type": "object",
                        "properties": skill.parameters.get("properties", {}),
                        "required": skill.parameters.get("required", []),
                    },
                },
            })
        return tools

    def summary(self) -> str:
        """Return a text summary of all enabled skills (for System Prompt)."""
        lines = []
        for skill in self.list_enabled():
            lines.append(f"- **{skill.name}** ({skill.category}): {skill.description}")
        return "\n".join(lines) if lines else "(No skills registered)"
