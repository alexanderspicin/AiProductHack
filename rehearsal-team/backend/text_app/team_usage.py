"""Observe Pipecat usage without inserting an alternative voice processor."""
from pipecat.frames.frames import LLMFullResponseStartFrame, LLMFullResponseEndFrame, MetricsFrame, LLMMessagesAppendFrame
from pipecat.metrics.metrics import LLMUsageMetricsData
from pipecat.observers.base_observer import BaseObserver


class TrainingUsageObserver(BaseObserver):
    def __init__(self, training, llm):
        super().__init__()
        self.budget = training.service.agent.budget
        self.training = training
        self.text_frames = set()
        self.model = training.session.settings.model
        self.llm = llm
        self.pending = None
        self.seen = set()

    async def on_push_frame(self, data):
        if isinstance(data.frame, LLMMessagesAppendFrame) and data.frame.id not in self.text_frames:
            self.text_frames.add(data.frame.id)
            for message in data.frame.messages:
                if message.get('role') == 'user' and isinstance(message.get('content'), str):
                    await self.training.user_message(message['content'])
        if data.source is not self.llm or data.frame.id in self.seen:
            return
        frame = data.frame
        if not isinstance(frame, (LLMFullResponseStartFrame, LLMFullResponseEndFrame, MetricsFrame)):
            return
        self.seen.add(frame.id)
        if isinstance(frame, LLMFullResponseStartFrame):
            self.finish_unknown()
            self.pending = self.budget.reserve("text_turn")
        elif isinstance(frame, MetricsFrame):
            for metric in frame.data:
                if not isinstance(metric, LLMUsageMetricsData):
                    continue
                reservation = self.pending or self.budget.reserve("text_turn")
                usage = metric.value
                self.budget.record(reservation, self.model, {
                    "prompt_tokens": usage.prompt_tokens, "completion_tokens": usage.completion_tokens,
                    "total_tokens": usage.total_tokens,
                    "prompt_tokens_details": {"cached_tokens": usage.cache_read_input_tokens or 0},
                    "completion_tokens_details": {"reasoning_tokens": usage.reasoning_tokens or 0},
                })
                self.budget.finish(reservation, "completed")
                self.pending = None
        elif isinstance(frame, LLMFullResponseEndFrame):
            self.finish_unknown()

    def finish_unknown(self):
        if self.pending:
            self.budget.finish(self.pending, "cancelled")
            self.pending = None
