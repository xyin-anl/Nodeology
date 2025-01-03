"""
Copyright (c) 2024, UChicago Argonne, LLC. All rights reserved.

Copyright 2024. UChicago Argonne, LLC. This software was produced
under U.S. Government contract DE-AC02-06CH11357 for Argonne National
Laboratory (ANL), which is operated by UChicago Argonne, LLC for the
U.S. Department of Energy. The U.S. Government has rights to use,
reproduce, and distribute this software.  NEITHER THE GOVERNMENT NOR
UChicago Argonne, LLC MAKES ANY WARRANTY, EXPRESS OR IMPLIED, OR
ASSUMES ANY LIABILITY FOR THE USE OF THIS SOFTWARE.  If software is
modified to produce derivative works, such modified software should
be clearly marked, so as not to confuse it with the version available
from ANL.

Additionally, redistribution and use in source and binary forms, with
or without modification, are permitted provided that the following
conditions are met:

    * Redistributions of source code must retain the above copyright
      notice, this list of conditions and the following disclaimer.

    * Redistributions in binary form must reproduce the above copyright
      notice, this list of conditions and the following disclaimer in
      the documentation and/or other materials provided with the
      distribution.

    * Neither the name of UChicago Argonne, LLC, Argonne National
      Laboratory, ANL, the U.S. Government, nor the names of its
      contributors may be used to endorse or promote products derived
      from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY UChicago Argonne, LLC AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL UChicago
Argonne, LLC OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.
"""

### Initial Author <2024>: Xiangyu Yin

from typing import List
from nodeology.node import Node, record_messages
from nodeology.state import State


class PlanningState(State):
    plan: str
    planner_knowledge: str
    plan_history: List[str]


# Define the planner template
planner = Node(
    node_type="planner",
    prompt_template="""# HISTORY:
{history_text}

# Instructions:
Plan a new step based on previous steps in HISTORY.""",
    sink=["plan"],
)


def planner_pre_process(state, client, **kwargs):
    record_messages(
        state, [("assistant", "I will plan a solution based on the history.", "green")]
    )

    # Build history text from sources
    history_text = ""
    sources = kwargs.get("source", ["plan_history", "quality_history"])
    for i in range(len(state[sources[0]])):
        history_text += f"## Step {i+1}:\n"
        for source in sources:
            history_text += f"### {source.capitalize()}:\n{state[source][i]}\n"

    # Add history_text to kwargs so template can access it
    kwargs["history_text"] = history_text
    return state


def planner_post_process(state, client, **kwargs):
    record_messages(
        state,
        [
            ("assistant", "Here is the plan:", "green"),
            ("assistant", state["plan"], "blue"),
        ],
    )

    # Update history if needed
    sink_history = kwargs.get("sink_history", "plan_history")
    if sink_history in state:
        state[sink_history] = state[sink_history][-state["history_length"] :] + [
            state["plan"]
        ]
    return state


# Add pre/post processing to template
planner.pre_process = planner_pre_process
planner.post_process = planner_post_process
