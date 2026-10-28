"""Development-only fakes so the notebook can be smoke-tested offline (MINIPROJECT_TEST_MODE=1)."""
import os
import typing
from typing import Any, Optional

from pydantic import BaseModel
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda


def dummy(schema, name=''):
    """Build a plausible instance of a pydantic schema / type for testing."""
    origin = typing.get_origin(schema)
    args = typing.get_args(schema)
    if origin is typing.Union:
        non_none = [a for a in args if a is not type(None)]
        return dummy(non_none[0], name)
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        values = {fname: dummy(f.annotation, fname) for fname, f in schema.model_fields.items()}
        if 'source' in values:
            values['source'] = 'delta_lake_vldb2020.pdf'
        if 'page' in values:
            values['page'] = 1
        if 'quote' in values:
            values['quote'] = 'transaction log'
        if 'index' in values:
            values['index'] = 0
        return schema(**values)
    if origin is list:
        return [dummy(args[0], name) for _ in range(3)]
    if origin is dict:
        return {'example metric': '42'}
    if schema is bool:
        return name not in ('needs_web_search',)
    if schema is int:
        return 4
    if schema is float:
        return 0.8
    if schema is str:
        return f'test {name} text'
    return None


class FakeChatModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return 'fake-chat'

    def _generate(self, messages, stop=None, run_manager=None, **kwargs: Any) -> ChatResult:
        tools = kwargs.get('tools')
        human = next((m.content for m in messages if isinstance(m, HumanMessage)), '')
        n_tool = sum(isinstance(m, ToolMessage) for m in messages)
        if tools:
            if 'Which one' in human:
                msg = AIMessage(content='Could you clarify which systems you want to compare?')
            elif n_tool == 0:
                first = 'search_web' if 'latest stable release' in human else 'search_documents'
                msg = AIMessage(content='Thought: check the documents first.',
                                tool_calls=[{'name': first, 'args': {'query': human[:60]}, 'id': 'call_1',
                                             'type': 'tool_call'}])
            elif n_tool == 1 and 'newer' in human:
                msg = AIMessage(content='Thought: the papers do not cover recent features.',
                                tool_calls=[{'name': 'search_web', 'args': {'query': 'delta lake new features'},
                                             'id': 'call_2', 'type': 'tool_call'}])
            else:
                msg = AIMessage(content='Final answer from tools [Source: delta_lake_vldb2020.pdf, Page: 1]')
        else:
            msg = AIMessage(content='Answer.\nKey points:\n- point one\n[Source: delta_lake_vldb2020.pdf, Page: 1]')
        msg.usage_metadata = {'input_tokens': 120, 'output_tokens': 30, 'total_tokens': 150}
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def bind_tools(self, tools, **kwargs):
        from langchain_core.utils.function_calling import convert_to_openai_tool
        return self.bind(tools=[convert_to_openai_tool(t) for t in tools])

    def with_structured_output(self, schema, include_raw=False, **kwargs):
        if include_raw:
            return RunnableLambda(lambda _: {'raw': AIMessage(content='{}'), 'parsed': dummy(schema), 'parsing_error': None})
        return RunnableLambda(lambda _: dummy(schema))


def make_fake_corpus(directory, filenames):
    from fpdf import FPDF
    os.makedirs(directory, exist_ok=True)
    for fname in filenames:
        path = os.path.join(directory, fname)
        if os.path.exists(path):
            continue
        pdf = FPDF()
        pdf.set_font('Helvetica', size=11)
        topic = fname.split('_')[0]
        for page in range(3):
            pdf.add_page()
            body = (f'This is page {page + 1} of the {topic} paper. It discusses transaction logs, lineage, '
                    f'columnar storage, fault tolerance and query optimization in {topic}. ') * 12
            pdf.multi_cell(0, 6, body)
        pdf.output(path)
