> [!WARNING]
> **This project is archived and no longer maintained.**
>
> Nodeology was built on `langgraph` 0.2.x to give researchers a prompt-template-driven node abstraction over LangGraph's state machine. Since then, LangGraph has evolved substantially (0.6.x and beyond) — the new [Functional API](https://langchain-ai.github.io/langgraph/concepts/functional_api/) (`@task` / `@entrypoint`), native [interrupts](https://langchain-ai.github.io/langgraph/concepts/human_in_the_loop/) for human-in-the-loop, durable execution, and improved checkpointers now cover most of what Nodeology was created to simplify.
>
> More fundamentally, foundation models have become substantially more capable since this project began. For many tasks that previously required a hand-designed graph of nodes with deterministic control flow, modern models can now plan, decide, and execute end-to-end on their own — given a clear objective and a set of tools. The need for an explicit, author-it-yourself state machine has shrunk accordingly, and agent-style approaches (where the model drives the loop) are often simpler and more robust than a fixed graph.
>
> **For new projects**, we recommend:
> - **Agent SDKs** when you want the model to drive the loop with tool use — these handle planning, tool calling, and multi-turn execution out of the box:
>   - [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) — lightweight Python framework for building agentic workflows with tools, handoffs, and guardrails.
>   - [Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk/overview) — Anthropic's SDK for building agents with Claude, with first-class support for tool use, sub-agents, and long-horizon tasks.
> - **LangGraph** (latest) when you genuinely need explicit control flow, durability, or multi-agent coordination. The [Functional API](https://langchain-ai.github.io/langgraph/concepts/functional_api/) offers a similarly declarative experience to Nodeology's `Node` abstraction.
>
> **Existing users**: this repo will continue to install and run against `langgraph<=0.2.45` (see `requirements.txt`), but no further updates, bug fixes, or feature work are planned. Downstream projects such as [PEAR](https://arxiv.org/abs/2410.09034) and [AutoScriptCopilot](https://github.com/xyin-anl/AutoScriptCopilot) remain functional with the pinned versions.

<div align="center">
  <img src="assets/logo.jpg" alt="Nodeology Logo" width="600"/>
  <h3></h3>
</div>

## 🤖 Foundation AI-Enhanced Scientific Workflow

Foundation AI holds enormous potential for scientific research, especially in analyzing unstructured data, automating complex reasoning tasks, and simplifying human-computer interactions. However, integrating foundation AI models like LLMs and VLMs into scientific workflows poses challenges: handling diverse data types beyond text and images, managing model inaccuracies (hallucinations), and adapting general-purpose models to highly specialized scientific contexts.

`nodeology` addresses these challenges by combining the strengths of foundation AI with traditional scientific methods and expert oversight. Built on `langgraph`'s state machine framework, it simplifies creating robust, AI-driven workflows through an intuitive, accessible interface. Originally developed at Argonne National Lab, the framework enables researchers—especially those without extensive programming experience—to quickly design and deploy full-stack AI workflows simply using prompt templates and existing functions as reusable nodes.

Key features include:

- Easy creation of AI-integrated workflows without complex syntax
- Flexible and composable node architecture for various tasks
- Seamless human-in-the-loop interactions for expert oversight
- Portable workflow templates for collaboration and reproducibility
- Quickly spin up simple chatbots for immediate AI interaction
- Built-in tracing and telemetry for workflow monitoring and optimization

## 🚀 Getting Started

### Install the package

To use the latest development version:

```bash
pip install git+https://github.com/xyin-anl/Nodeology.git
```

To use the latest release version:

```bash
pip install nodeology
```

### Access foundation models

Nodeology supports various cloud-based/local foundation models via [LiteLLM](https://docs.litellm.ai/docs/), see [provider list](https://docs.litellm.ai/docs/providers). Most of cloud-based models usage requires setting up API key. For example:

```bash
# For OpenAI models
export OPENAI_API_KEY='your-api-key'

# For Anthropic models
export ANTHROPIC_API_KEY='your-api-key'

# For Gemini models
export GEMINI_API_KEY='your-api-key'

# For Together AI hosted open weight models
export TOGETHER_API_KEY='your-api-key'
```

> **💡 Tip:** The field of foundation models is evolving rapidly with new and improved models emerging frequently. As of **February 2025**, we recommend the following models based on their strengths:
>
> - **gpt-4o**: Excellent for broad general knowledge, writing tasks, and conversational interactions
> - **o3-mini**: Good balance of math, coding, and reasoning capabilities at a lower price point
> - **anthropic/claude-3.7**: Strong performance in general knowledge, math, science, and coding with well-constrained outputs
> - **gemini/gemini-2.0-flash**: Effective for general knowledge tasks with a large context window for processing substantial information
> - **together_ai/deepseek-ai/DeepSeek-R1**: Exceptional reasoning, math, science, and coding capabilities with transparent thinking processes

**For Argonne Users:** if you are within Argonne network, you will have access to OpenAI's models through Argonne's ARGO inference service and ALCF's open weights model inference service for free. Please check this [link](https://gist.github.com/xyin-anl/0cc744a7862e153414857b15fe31b239) to see how to use them

### Langfuse Tracing (Optional)

Nodeology supports [Langfuse](https://langfuse.com/) for observability and tracing of LLM/VLM calls. To use Langfuse:

1. Set up a Langfuse account and get your API keys
2. Configure Langfuse with your keys:

```bash
# Set environment variables
export LANGFUSE_PUBLIC_KEY='your-public-key'
export LANGFUSE_SECRET_KEY='your-secret-key'
export LANGFUSE_HOST='https://cloud.langfuse.com'  # Or your self-hosted URL
```

Or configure programmatically:

```python
from nodeology.client import configure_langfuse

configure_langfuse(
    public_key='your-public-key',
    secret_key='your-secret-key',
    host='https://cloud.langfuse.com'  # Optional
)
```

### Chainlit Interface (Optional)

Nodeology supports [Chainlit](https://docs.chainlit.io/get-started/overview) for creating chat-based user interfaces. To use this feature, simply set `ui=True` when running your workflow:

```python
# Create your workflow
workflow = MyWorkflow()

# Run with UI enabled
workflow.run(ui=True)
```

This will automatically launch a Chainlit server with a chat interface for interacting with your workflow. The interface preserves your workflow's state and configuration, allowing users to interact with it through a user-friendly chat interface.

When the Chainlit server starts, you can access the interface through your web browser at `http://localhost:8000` by default.

## 🧪 Illustrating Examples

### [Writing Improvement](https://github.com/xyin-anl/Nodeology/examples/writing_improvement.py)

<div align="left">
      <a href="https://www.youtube.com/watch?v=6wRJnV0OCWA">
         <img src="https://img.youtube.com/vi/6wRJnV0OCWA/0.jpg" style="width:100%;">
      </a>
</div>

### [Trajectory Analysis](https://github.com/xyin-anl/Nodeology/examples/trajectory_analysis.py)

<div align="left">
      <a href="https://www.youtube.com/watch?v=4c-TmLCWd_U">
         <img src="https://img.youtube.com/vi/4c-TmLCWd_U/0.jpg" style="width:100%;">
      </a>
</div>

## 🔬 Scientific Applications

- [PEAR: Ptychography automation framework](https://arxiv.org/abs/2410.09034)
- [AutoScriptCopilot: TEM experiment control](https://github.com/xyin-anl/AutoScriptCopilot)

## 👥 Contributing & Collaboration

We welcome comments, feedbacks, bugs report, code contributions and research collaborations. Please refer to CONTRIBUTING.md

If you find `nodeology` useful and may inspire your research, please use the **Cite this repository** function
