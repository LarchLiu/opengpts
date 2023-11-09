from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List, Optional, Sequence, Type

from langchain.callbacks.tracers.schemas import Run
from langchain.pydantic_v1 import BaseModel, create_model
from langchain.schema.chat_history import BaseChatMessageHistory
from langchain.schema.messages import BaseMessage
from langchain.schema.runnable.base import Runnable, RunnableBinding, RunnableLambda
from langchain.schema.runnable.config import RunnableConfig
from langchain.schema.runnable.passthrough import RunnablePassthrough
from langchain.schema.runnable.utils import ConfigurableFieldSpec


class RunnableWithMessageHistory(RunnableBinding):
    factory: Callable[[str], BaseChatMessageHistory]

    input_key: str

    output_key: Optional[str]
    history_key: str = "messages"

    def __init__(
        self,
        runnable: Runnable,
        factory: Callable[[str], BaseChatMessageHistory],
        input_key: str,
        output_key: Optional[str] = None,
        history_key: str = "messages",
        **kwargs: Any,
    ) -> None:
        bound = RunnablePassthrough.assign(
            **{history_key: RunnableLambda(self._enter_history, self._aenter_history)}
        ) | runnable.with_listeners(on_end=self._exit_history)
        super().__init__(
            factory=factory,
            input_key=input_key,
            output_key=output_key,
            bound=bound,
            **kwargs,
        )

    @property
    def config_specs(self) -> Sequence[ConfigurableFieldSpec]:
        return super().config_specs + [
            ConfigurableFieldSpec(
                id="thread_id",
                annotation=str,
                name="",
                description="",
                default="",
            )
        ]

    def config_schema(
        self, *, include: Optional[Sequence[str]] = None
    ) -> Type[BaseModel]:
        return super(RunnableBinding, self).config_schema(include=include)

    def with_config(
        self,
        config: Optional[RunnableConfig] = None,
        **kwargs: Any,
    ) -> RunnableWithMessageHistory:
        return super(RunnableBinding, self).with_config(config, **kwargs)

    def with_types(
        self,
        input_type: Optional[BaseModel] = None,
        output_type: Optional[BaseModel] = None,
    ) -> RunnableBinding:
        return super(RunnableBinding, self).with_types(
            input_type=input_type, output_type=output_type
        )

    def get_input_schema(
        self, config: Optional[RunnableConfig] = None
    ) -> Type[BaseModel]:
        super_schema = super().get_input_schema(config)
        if super_schema.__custom_root_type__ is not None:
            # The schema is not correct so we'll default to dict with input_key
            return create_model(  # type: ignore[call-overload]
                "RunnableWithChatHistoryInput",
                **{self.input_key: (str, ...)},
            )
        else:
            return super_schema

    def _enter_history(
        self, input: Dict[str, Any], config: RunnableConfig
    ) -> List[BaseMessage]:
        hist: BaseChatMessageHistory = config["configurable"]["message_history"]
        return hist.messages.copy() + [input[self.input_key]]

    async def _aenter_history(
        self, input: Dict[str, Any], config: RunnableConfig
    ) -> List[BaseMessage]:
        return await asyncio.get_running_loop().run_in_executor(
            None, self._enter_history, input, config
        )

    def _exit_history(self, run: Run, config: RunnableConfig) -> None:
        hist: BaseChatMessageHistory = config["configurable"]["message_history"]
        # Add the input message
        hist.add_message(run.inputs[self.input_key])
        # Find the output messages
        for m in run.outputs[self.output_key]:
            hist.add_message(m)

    def _merge_configs(self, *configs: Optional[RunnableConfig]) -> RunnableConfig:
        config = super()._merge_configs(*configs)
        print(config)
        # extract thread_id
        config["configurable"] = config.get("configurable", {})
        try:
            thread_id = config["configurable"]["thread_id"]
        except KeyError:
            example_input = {self.input_key: "foo"}
            raise ValueError(
                "thread_id is required when using .with_message_history()"
                "\nPass it in as part of the config argument to .invoke() or .stream()"
                f'\neg. chain.invoke({example_input}, {{"configurable": {{"thread_id":'
                ' "123"}})'
            )
        del config["configurable"]["thread_id"]
        # attach message_history
        config["configurable"]["message_history"] = self.factory(  # type: ignore
            session_id=thread_id,
        )
        return config
