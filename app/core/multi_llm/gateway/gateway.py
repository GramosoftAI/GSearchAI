import logging
from typing import Optional

from ..config.schema import LLMConfigModel, TaskConfig
from ..router.router import LLMRouter
from ..types import LLMRequest, LLMResponse, TaskType

log = logging.getLogger(__name__)

class LLMGateway:
    def __init__(self, config: LLMConfigModel, router: LLMRouter):
        self.config = config
        self.router = router

    def get_task_config(self, task_type: TaskType) -> Optional[TaskConfig]:
        """Retrieve the TaskConfig for a given task type."""
        return self.config.tasks.get(task_type.value)

    async def chat(self, task_type: TaskType, request: LLMRequest) -> LLMResponse:
        """
        Executes a chat request against the multi-LLM router, enforcing task-specific configurations.
        """
        task_config = self.get_task_config(task_type)
        if not task_config:
            log.warning(f"No specific task configuration found for {task_type}. Falling back to default routing if available.")
        else:
            # Enforce task-specific configurations on the request
            request.task_type = task_type
            
            # Use task-specific parameters if they aren't explicitly overridden in the request
            if request.temperature == 0.2: # default from LLMRequest
                request.temperature = task_config.temperature
                
            if task_config.json_mode and not request.json_schema:
                request.json_schema = {} # Empty dict to signify JSON mode without specific schema
                
        return await self.router.chat(task_type.value, request)
