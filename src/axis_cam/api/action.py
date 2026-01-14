"""Action Rules API module.

This module provides access to action rules on AXIS devices
via the VAPIX action API.

API Endpoints:
    - /config/rest/action/v1 (REST API)
"""

from typing import Any

from axis_cam.api.base import BaseAPI
from axis_cam.models import ActionConfig, ActionRule, ActionTemplate


class ActionAPI(BaseAPI):
    """API module for action rules configuration.

    This module provides methods to retrieve and manage action rules:
    - Rule listing and details
    - Action templates
    - Rule conditions and responses

    Example:
        >>> async with AxisCamera("192.168.1.10", "admin", "pass") as camera:
        ...     config = await camera.action.get_config()
        ...     for rule in config.rules:
        ...         print(f"Rule: {rule.name} - Enabled: {rule.enabled}")
    """

    REST_PATH = "/config/rest/action/v1"

    async def get_config(self) -> ActionConfig:
        """Get complete action configuration.

        Returns:
            ActionConfig model with all action rules.
        """
        try:
            response = await self._get(self.REST_PATH, params={"recursive": "true"})
            data = response.get("data", {})
            return self._parse_config(data)
        except Exception:
            return ActionConfig()

    async def get_rules(self) -> list[ActionRule]:
        """Get list of action rules.

        Returns:
            List of ActionRule models.
        """
        config = await self.get_config()
        return config.rules

    async def get_templates(self) -> list[ActionTemplate]:
        """Get available action templates.

        Returns:
            List of ActionTemplate models.
        """
        config = await self.get_config()
        return config.templates

    async def get_rule(self, rule_id: str) -> ActionRule | None:
        """Get a specific action rule by ID.

        Args:
            rule_id: Rule identifier.

        Returns:
            ActionRule model or None if not found.
        """
        rules = await self.get_rules()
        for rule in rules:
            if rule.id == rule_id:
                return rule
        return None

    def _parse_config(self, data: dict[str, Any]) -> ActionConfig:
        """Parse action configuration response.

        Args:
            data: Raw API response data.

        Returns:
            ActionConfig model instance.
        """
        # Parse rules
        rules = []
        rules_data = data.get("rules", {})
        for rule_id, rule_info in rules_data.items():
            if isinstance(rule_info, dict):
                rules.append(self._parse_rule(rule_id, rule_info))

        # Parse templates
        templates = []
        templates_data = data.get("templates", {})
        for template_id, template_info in templates_data.items():
            if isinstance(template_info, dict):
                templates.append(self._parse_template(template_id, template_info))

        return ActionConfig(
            rules=rules,
            templates=templates,
        )

    def _parse_rule(self, rule_id: str, data: dict[str, Any]) -> ActionRule:
        """Parse action rule data.

        Args:
            rule_id: Rule identifier.
            data: Rule configuration data.

        Returns:
            ActionRule model.
        """
        return ActionRule(
            id=rule_id,
            name=data.get("name", ""),
            enabled=data.get("enabled", False),
            primary_condition=data.get("primaryCondition", ""),
            conditions=data.get("conditions", []),
            actions=data.get("actions", []),
        )

    def _parse_template(self, template_id: str, data: dict[str, Any]) -> ActionTemplate:
        """Parse action template data.

        Args:
            template_id: Template identifier.
            data: Template configuration data.

        Returns:
            ActionTemplate model.
        """
        return ActionTemplate(
            id=template_id,
            name=data.get("name", ""),
            template_type=data.get("type", ""),
            parameters=data.get("parameters", {}),
        )
