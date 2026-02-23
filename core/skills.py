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

    def __init__(self):
        self._registry: Dict[str, SkillDefinition] = {}

    def register(self, skill: SkillDefinition) -> None:
        """Register a skill."""
        self._registry[skill.name] = skill

    def skill(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        category: str = "general",
        enabled: bool = True,
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
            ))
            return func
        return decorator

    def enable(self, name: str) -> None:
        if name in self._registry:
            self._registry[name].enabled = True

    def disable(self, name: str) -> None:
        if name in self._registry:
            self._registry[name].enabled = False

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
