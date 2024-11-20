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

import os, logging
import json, yaml
import getpass
from datetime import datetime
from jsonschema import validate
from typing import Dict, Any, Optional, List, Union
import ast, operator, traceback
from abc import ABC, abstractmethod

# Ensure that TypedDict is imported correctly for all Python versions
try:
    from typing import TypedDict, get_type_hints, is_typeddict
except ImportError:
    from typing_extensions import TypedDict, get_type_hints, is_typeddict

from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StateSnapshot
from langgraph.checkpoint.memory import MemorySaver

from nodeology.log import (
    logger,
    log_print_color,
    add_logging_level,
    setup_logging,
)
from nodeology.client import get_client, LLM_Client, VLM_Client
from nodeology.state import State, process_state_definitions, _resolve_state_type
from nodeology.node import Node
from nodeology.prebuilt import prebuilt_states, prebuilt_nodes


class Workflow(ABC):
    """Abstract base class for workflow management.
    
    The Workflow class provides a framework for creating and managing stateful workflows
    that combine language models, vision models, and custom processing nodes. It handles
    state management, logging, error recovery, and workflow execution.

    Key Features:
        - State Management: Maintains workflow state with type validation and history
        - Error Recovery: Automatic state restoration on failures
        - Logging: Comprehensive logging with custom levels
        - Checkpointing: Automatic state checkpointing
        - Human Interaction: Handles user input and interrupts
        - Model Integration: Supports both LLM and VLM clients

    Attributes:
        name (str): Unique workflow identifier
        llm_client (LLM_Client): Language model client for text processing
        vlm_client (Optional[VLM_Client]): Vision model client for image processing
        exit_commands (List[str]): Commands that will trigger workflow termination
        save_artifacts (bool): Whether to save state artifacts to disk
        debug_mode (bool): Enable detailed debug logging
        max_history (int): Maximum number of states to keep in history
        state_schema (Type[State]): Type definition for workflow state
        state_history (List[StateSnapshot]): History of workflow states
        state_index (int): Current state index
        graph (CompiledStateGraph): Compiled workflow graph
        langgraph_config (dict): Configuration for langgraph execution

    Example:
        ```python
        class MyWorkflow(Workflow):
            def create_workflow(self):
                # Define workflow structure
                self.workflow = StateGraph(self.state_schema)
                self.workflow.add_node("start", start_node)
                self.workflow.add_node("process", process_node)
                self.workflow.add_edge("start", "process")
                self.workflow.set_entry_point("start")
                self.graph = self.workflow.compile()

        # Create and run workflow
        workflow = MyWorkflow(
            name="example",
            llm_name="gpt-4",
            save_artifacts=True
        )
        result = workflow.run()
        ```
    """

    class StateEncoder(json.JSONEncoder):
        """Custom JSON encoder for serializing workflow states.
        
        Handles special data types and objects that aren't JSON-serializable by default:
        - Objects with to_dict() methods
        - bytes objects (converted to UTF-8 strings)
        - set objects (converted to lists)
        - Objects with __dict__ attributes
        
        Args:
            obj: Object to serialize
            
        Returns:
            JSON-serializable representation of the object
            
        Raises:
            TypeError: If object cannot be serialized
        """
        def default(self, obj):
            try:
                if hasattr(obj, "to_dict"):
                    return obj.to_dict()
                if hasattr(obj, "__dict__"):
                    # Handle common types that might need special treatment
                    if isinstance(obj, bytes):
                        return obj.decode("utf-8")
                    if isinstance(obj, set):
                        return list(obj)
                    return obj.__dict__
                return super().default(obj)
            except TypeError as e:
                logger.warning(
                    f"Could not serialize object of type {type(obj)}: {str(e)}"
                )
                return str(obj)

    def __init__(
        self,
        name: Optional[str] = None,
        llm_name: str = "gpt-4o",
        vlm_name: Optional[str] = None,
        state_defs: Optional[Union[List, State]] = None,
        exit_commands: Optional[List[str]] = None,
        save_artifacts: bool = True,
        debug_mode: bool = False,
        max_history: int = 1000,
        **kwargs,
    ) -> None:
        """Initialize workflow

        Args:
            name: Workflow name (defaults to class name + timestamp)
            llm_name: Name of LLM model to use
            vlm_name: Optional name of VLM model
            state_defs: State definitions (defaults to class state_schema or State)
            exit_commands: List of commands that will exit the workflow
            save_artifacts: Whether to save state artifacts
            debug_mode: Enable debug logging
            max_history: Maximum number of states to keep in history
        """
        # Generate default name if none provided
        self.name = (
            name
            or f"{self.__class__.__name__}_{datetime.now().strftime('%m_%d_%Y_%H_%M_%S')}"
        )
        if not self.name:
            raise ValueError("Workflow name cannot be empty")

        # Create clients
        self.llm_client = get_client(llm_name)
        assert isinstance(self.llm_client, LLM_Client), "Invalid LLM client"
        if vlm_name:
            self.vlm_client = get_client(vlm_name)
            assert isinstance(self.vlm_client, VLM_Client), "Invalid VLM client"
        else:
            self.vlm_client = None
            logger.warning(
                "VLM client not provided - vision features will be unavailable"
            )

        # Store configuration
        self.exit_commands = (
            exit_commands
            if exit_commands
            else [
                "stop workflow",
                "quit workflow",
                "terminate workflow",
            ]
        )
        self.save_artifacts = save_artifacts
        self.debug_mode = debug_mode
        self.max_history = max_history
        self.kwargs = kwargs

        # Process state definitions
        if is_typeddict(state_defs):
            self.state_schema = state_defs
        elif isinstance(state_defs, list):
            self.state_schema = self._compile_state_definitions(state_defs)
        else:
            self.state_schema = getattr(self, "state_schema", State)

        # Setup logging and initialize workflow
        self._setup_logging()
        self.create_workflow()
        self.initialize()

    def _compile_state_definitions(self, state_defs):
        """Compile state definitions into a State class"""
        annotations = {}

        for state_def in state_defs:
            if isinstance(state_def, tuple) and len(state_def) == 2:
                name, type_hint = state_def
                if isinstance(type_hint, str):
                    # Use _resolve_state_type to get the actual type
                    type_hint = _resolve_state_type(type_hint)
                annotations[name] = type_hint
            elif isinstance(state_def, type) and is_typeddict(state_def):
                # Use get_type_hints to retrieve annotations from the TypedDict
                annotations.update(get_type_hints(state_def))
            else:
                raise ValueError(f"Invalid state definition format: {state_def}")

        # Dynamically create a new TypedDict class with the collected annotations
        CompiledState = TypedDict("CompiledState", annotations)
        return CompiledState

    def _setup_logging(self, base_dir: Optional[str] = None) -> None:
        """Setup workflow-specific logging configuration.
        
        Configures logging with custom levels and file handlers.
        
        Args:
            base_dir: Optional base directory for log files
        """
        # Set up basic workflow information
        self.user_name = getpass.getuser()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_name = f"{self.name}_{timestamp}"
        self.log_path = os.path.join("logs", self.name)

        # Add custom logging levels if not already present
        if not hasattr(logging, "PRINTLOG"):
            add_logging_level("PRINTLOG", logging.INFO + 5)
        if not hasattr(logging, "LOGONLY"):
            add_logging_level("LOGONLY", logging.INFO + 1)

        # Setup logging using the log_utils configuration
        setup_logging(
            log_dir=self.log_path,
            log_name=self.log_name,
            debug_mode=self.debug_mode,
            base_dir=base_dir,
        )

        # Log initial workflow configuration
        logger.logonly("########## Settings ##########")
        logger.logonly(f"Workflow name: {self.name}")
        logger.logonly(f"User name: {self.user_name}")
        logger.logonly(f"Debug mode: {self.debug_mode}")
        logger.logonly("##############################")

    def save_state(self, current_state: Optional[StateSnapshot] = None) -> None:
        """Save the current workflow state to history and optionally to disk.
        
        Args:
            current_state: State snapshot to save (fetched if None)
            
        Maintains a rolling history window and saves state files if save_artifacts is enabled.
        """
        try:
            if current_state is None:
                current_state = self.graph.get_state(self.langgraph_config)

            # Add to history
            self.state_history.append(current_state)
            current_state_values = current_state.values

            # Maintain rolling history window
            if len(self.state_history) > self.max_history:
                self.state_history = self.state_history[-self.max_history:]

            # Save state file if enabled
            if self.save_artifacts and not self.debug_mode:
                state_file = os.path.join(
                    self.log_path, f"state_{self.state_index}.json"
                )
                with open(state_file, "w", encoding="utf-8") as f:
                    json.dump(current_state_values, f, indent=2, cls=self.StateEncoder)

            self.state_index += 1

        except Exception as e:
            logger.error(f"Failed to save state: {str(e)}")
            if self.debug_mode:
                raise

    def load_state(self, state_index: int) -> None:
        """Load a previous workflow state by index.
        
        Args:
            state_index: Index of state to load
            
        Raises:
            ValueError: If state file not found or schema mismatch
        """
        # Try loading from recent history first
        if state_index < self.state_index and state_index >= (
            self.state_index - self.max_history
        ):
            state = self.state_history[-self.state_index + state_index]
            state_values = state.values
        else:
            # Fall back to loading from file
            state_file = os.path.join(self.log_path, f"state_{state_index}.json")
            if os.path.exists(state_file):
                with open(state_file, "r", encoding="utf-8") as f:
                    state_values = json.load(f)
            else:
                raise ValueError(f"State file not found: {state_file}")

        # Validate loaded state against current schema
        annotations = get_type_hints(self.state_schema)
        for field in annotations:
            if field not in state_values:
                raise ValueError("Loaded state does not match current schema")

        # Update graph state and save
        self.graph.update_state(self.langgraph_config, state_values)
        self.save_state()

    def update_state(
        self,
        values: Optional[Dict[str, Any]] = None,
        current_state: Optional[StateSnapshot] = None,
        human_input: Optional[str] = None,
        as_node: Optional[Node] = None,
    ) -> None:
        """Update the workflow state with new values and/or human input.
        
        Handles nested updates, type validation, and error recovery.
        
        Args:
            values: Dictionary of state values to update
            current_state: Current state snapshot (fetched if None)
            human_input: Human input to add to messages/conversation
            as_node: Node to attribute the update to
            
        Raises:
            TypeError: If provided values don't match schema types
            ValueError: If invalid fields are provided in debug mode
        """
        try:
            current_state = (
                self.graph.get_state(self.langgraph_config)
                if current_state is None
                else current_state
            )
            new_state_values = current_state.values.copy()

            annotations = get_type_hints(self.state_schema)

            if values:
                # Validate fields before updating
                invalid_fields = [field for field in values if field not in annotations]
                if invalid_fields:
                    if self.debug_mode:  # Only raise in debug mode
                        raise ValueError(f"Invalid fields in update: {invalid_fields}")
                    else:
                        logger.warning(
                            f"Ignoring invalid fields in update: {invalid_fields}"
                        )
                        # Filter out invalid fields
                        values = {k: v for k, v in values.items() if k in annotations}

                def update_nested(current: dict, updates: dict):
                    """Recursively update nested dictionary with type validation."""
                    for k, v in updates.items():
                        if (
                            k in current
                            and isinstance(current[k], dict)
                            and isinstance(v, dict)
                        ):
                            update_nested(current[k], v)
                        else:
                            if k in annotations:
                                field_type = annotations[k]
                                if not self._validate_type(v, field_type):
                                    raise TypeError(
                                        f"Invalid type for {k}: expected {field_type}, got {type(v)}"
                                    )
                            current[k] = v

                update_nested(new_state_values, values)

            if human_input is not None:
                # Update message-related fields if they exist in schema
                for field, update in [
                    (
                        "messages",
                        lambda: new_state_values["messages"]
                        + [{"role": "user", "content": human_input}],
                    ),
                    (
                        "conversation",
                        lambda: new_state_values["conversation"]
                        + [{"role": "user", "content": human_input}],
                    ),
                    ("human_input", lambda: human_input),
                ]:
                    if field in annotations:
                        if field not in new_state_values:
                            new_state_values[field] = (
                                [] if field in ["messages", "conversation"] else ""
                            )
                        new_value = update()
                        field_type = annotations[field]
                        if not self._validate_type(new_value, field_type):
                            raise TypeError(
                                f"Invalid type for {field}: expected {field_type}, got {type(new_value)}"
                            )
                        new_state_values[field] = new_value

            self.graph.update_state(
                config=self.langgraph_config,
                values=new_state_values,
                as_node=as_node,
            )

        except Exception as e:
            logger.error(f"Error in update_state: {str(e)}\n{traceback.format_exc()}")
            if self.debug_mode:
                raise
            else:
                self._restore_last_valid_state()

    def _create_checkpoint(self) -> None:
        """Create a checkpoint of the current workflow state.
        
        Saves the current state to a checkpoint file if save_artifacts is enabled.
        """
        if self.save_artifacts and not self.debug_mode:
            state = self.graph.get_state(self.langgraph_config)
            checkpoint_file = os.path.join(self.log_path, "checkpoint.json")
            try:
                with open(checkpoint_file, "w", encoding="utf-8") as f:
                    json.dump(state.values, f, indent=2, cls=self.StateEncoder)
                logger.debug("Created checkpoint")
            except Exception as e:
                logger.error(f"Failed to create checkpoint: {str(e)}")

    def _restore_last_valid_state(self):
        """Attempt to restore the workflow to the last valid state.
        
        First tries recent history states, then falls back to checkpoint.
        Raises RuntimeError if no valid state can be restored.
        """
        # First try recent history
        for i in range(self.state_index - 1, max(-1, self.state_index - 4), -1):
            try:
                self.load_state(i)
                logger.info(f"Successfully restored to state {i}")
                return
            except Exception as e:
                logger.warning(f"Failed to restore state {i}: {str(e)}")

        # If that fails, try loading checkpoint
        checkpoint_file = os.path.join(self.log_path, "checkpoint.json")
        if os.path.exists(checkpoint_file):
            try:
                with open(checkpoint_file, "r", encoding="utf-8") as f:
                    checkpoint_state = json.load(f)
                self.graph.update_state(self.langgraph_config, checkpoint_state)
                self.save_state()
                logger.info("Successfully restored from checkpoint")
                return
            except Exception as e:
                logger.error(f"Failed to restore from checkpoint: {str(e)}")

        raise RuntimeError("Could not restore to any valid state")

    @abstractmethod
    def create_workflow(self):
        """Create the workflow graph structure"""
        pass

    def _validate_type(self, value: Any, expected_type: Any) -> bool:
        """Validate that a value matches the expected type.
        
        Handles complex types including:
        - Union types
        - List types with element validation
        - Dict types with key/value validation
        
        Args:
            value: Value to validate
            expected_type: Type to validate against
            
        Returns:
            bool: Whether the value matches the expected type
        """
        from typing import get_origin, get_args, Union

        origin_type = get_origin(expected_type)

        if origin_type is Union:
            return any(self._validate_type(value, t) for t in get_args(expected_type))
        elif origin_type is list:
            if not isinstance(value, list):
                return False
            elem_type = get_args(expected_type)[0]
            return all(self._validate_type(v, elem_type) for v in value)
        elif origin_type is dict:
            if not isinstance(value, dict):
                return False
            key_type, val_type = get_args(expected_type)
            return all(
                self._validate_type(k, key_type) and self._validate_type(v, val_type)
                for k, v in value.items()
            )
        else:
            return isinstance(value, expected_type)

    def initialize(self, init_values: Optional[Dict[str, Any]] = None) -> None:
        """Initialize the workflow state with proper None handling and type checking"""
        assert hasattr(self, "graph"), "Workflow graph must be defined"
        assert isinstance(
            self.graph, CompiledStateGraph
        ), "Graph must be a CompiledStateGraph instance"

        # Use get_type_hints to resolve actual types
        annotations = get_type_hints(self.state_schema)

        # Initialize default values for all state fields
        default_state = {}
        for field, field_type in annotations.items():
            if field_type in (str, int, float, bool):
                default_values = {str: "", int: 0, float: 0.0, bool: False}
                default_state[field] = default_values[field_type]
            elif field_type == list or (
                hasattr(field_type, "__origin__") and field_type.__origin__ is list
            ):
                default_state[field] = []
            elif field_type == dict or (
                hasattr(field_type, "__origin__") and field_type.__origin__ is dict
            ):
                default_state[field] = {}
            elif hasattr(field_type, "__origin__") and field_type.__origin__ is Union:
                # For Union types, use the first type's default value
                first_type = field_type.__args__[0]
                if first_type in (str, int, float, bool):
                    default_values = {str: "", int: 0, float: 0.0, bool: False}
                    default_state[field] = default_values[first_type]
                else:
                    default_state[field] = None
            else:
                default_state[field] = None

        # Validate input fields before updating
        if init_values:
            invalid_fields = [
                field for field in init_values if field not in annotations
            ]
            if invalid_fields and self.debug_mode:
                raise ValueError(f"Invalid fields in initialization: {invalid_fields}")

        # Update defaults with provided values
        if init_values:
            for field, value in init_values.items():
                if field in annotations:
                    if value is None:
                        # Keep the default value if None is provided
                        continue
                    field_type = annotations[field]
                    if not self._validate_type(value, field_type):
                        raise TypeError(
                            f"Invalid type for {field}: expected {field_type}, got {type(value)}"
                        )
                    default_state[field] = value

        self.langgraph_config = {"configurable": {"thread_id": self.log_name}}
        self.graph.update_state(
            config=self.langgraph_config,
            values=default_state,
        )

        self.state_index = 0
        self.state_history = []
        self.save_state()

    def run(self, init_values: Optional[Dict] = None) -> Dict:
        """Run the workflow until completion or interruption.
        
        Executes the workflow graph, handling human input and state management.
        
        Args:
            init_values: Optional initial state values
            
        Returns:
            Dict: Final workflow state values or error state
        """
        log_print_color(f"Starting {self.name} workflow for {self.user_name}", "green")

        # Initialize graph state
        graph_input = (
            self.graph.get_state(self.langgraph_config).values
            if init_values is None
            else init_values
        )
        error_state = None
        current_state = self.graph.get_state(self.langgraph_config)

        try:
            while True:
                # Run the graph until it needs input or reaches the end
                for _ in self.graph.stream(graph_input, self.langgraph_config):
                    current_state = self.graph.get_state(self.langgraph_config)
                    self.save_state()

                    # Check if we've reached the end
                    if (
                        current_state.next is None
                        or len(current_state.next) == 0
                        or END in current_state.next
                        or "END" in current_state.next
                    ):
                        return current_state.values if current_state else {}

                # Get human input when the graph needs it
                human_input = self._get_human_input()
                if self._should_exit(human_input):
                    return current_state.values if current_state else {}

                # Update state with human input and continue
                self.update_state(
                    human_input=human_input, as_node=current_state.next[0]
                )
                self.save_state()
                graph_input = None  # Reset input for next iteration

        except Exception as e:
            logger.error(f"Error during workflow execution: {str(e)}")
            error_state = {"error": str(e)}
            if self.debug_mode:
                raise
            return (
                error_state
                if error_state
                else current_state.values if current_state else {}
            )

    def _should_exit(self, cmd_input: str) -> bool:
        """Check if a command should exit the workflow.
        
        Args:
            cmd_input: Command string to check
            
        Returns:
            bool: True if command matches any exit command
        """
        return any(cmd in cmd_input.lower() for cmd in self.exit_commands)

    def _get_human_input(self, mode: str = "cmd") -> str:
        """Get and log input from the user.
        
        Args:
            mode: Input mode (currently only supports 'cmd')
            
        Returns:
            str: User input
            
        Raises:
            ValueError: If invalid input mode specified
        """
        if mode == "cmd":
            human_input = input(f"{self.user_name}: ")
        else:
            raise ValueError(f"Invalid input mode: {mode}")
        logger.logonly(f"{self.user_name}: {human_input}")
        return human_input

    def __enter__(self):
        """Context manager entry point.
        
        Returns:
            Workflow: Self for use in with statement
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit point with cleanup.
        
        Creates final checkpoint and cleans up logging handlers.
        """
        try:
            # Create checkpoint before cleanup
            self._create_checkpoint()

            # Store a reference to the root logger
            root_logger = logging.getLogger()

            # Clean up logging handlers safely
            handlers = root_logger.handlers[:]  # Create a copy of the list
            for handler in handlers:
                try:
                    # Flush any remaining logs
                    handler.flush()
                    # Remove handler from logger first
                    root_logger.removeHandler(handler)
                    # Then close the handler
                    handler.close()
                except Exception as e:
                    # Log error without using file handler
                    print(f"Warning during handler cleanup: {str(e)}")

            # Clean up any graph resources
            if hasattr(self, "graph"):
                # Add graph cleanup if needed
                pass

        except Exception as e:
            # Print error since logging may not be available
            print(f"Error during workflow cleanup: {str(e)}")
            if self.debug_mode:
                raise


def _validate_template_structure(template: Dict) -> None:
    """Validate the basic structure of a workflow template against schema.
    
    Required fields:
    - name: string
    - state_defs: array of state definitions
    - nodes: object containing node definitions
    - entry_point: string

    Optional fields:
    - llm: string (default: "gpt-4o")
    - vlm: string
    - exit_commands: array of strings
    - intervene_before: array of strings
    - checkpointer: string
    
    Args:
        template: Template dictionary to validate
        
    Raises:
        ValueError: If template structure is invalid
    """
    schema = {
        "type": "object",
        "required": ["name", "state_defs", "nodes", "entry_point"],
        "properties": {
            "name": {"type": "string", "minLength": 1},
            "state_defs": {"type": "array", "minItems": 1},
            "nodes": {"type": "object", "minProperties": 1},
            "entry_point": {"type": "string"},
            "llm": {"type": "string"},
            "vlm": {"type": "string"},
            "exit_commands": {"type": "array", "items": {"type": "string"}},
            "intervene_before": {"type": "array", "items": {"type": "string"}},
            "checkpointer": {"type": "string"},
        },
        "additionalProperties": False,
    }

    try:
        validate(instance=template, schema=schema)
    except Exception as e:
        raise ValueError(f"Invalid template structure: {str(e)}")


def _validate_nodes(nodes: Dict, node_registry: Dict) -> None:
    """Validate node configurations in the template.
    
    Checks:
    - Required fields presence
    - Node type validity
    - Prompt node specific configuration
    - Next/conditional logic validity
    
    Args:
        nodes: Dictionary of node configurations
        node_registry: Dictionary of available node types
        
    Raises:
        ValueError: If node configuration is invalid
    """
    for node_name, node_config in nodes.items():
        # Check required fields
        if "type" not in node_config:
            raise ValueError(f"Node {node_name} missing 'type' field")

        node_type = node_config["type"]

        # Validate by node type
        if node_type == "prompt":
            _validate_prompt_node(node_name, node_config)
        elif node_type not in node_registry:
            raise ValueError(
                f"Unknown node type: {node_type} (available: {list(node_registry.keys())})"
            )

        # Validate next/conditional logic
        if "next" not in node_config:
            raise ValueError(f"Node '{node_name}' missing 'next' field")

        # Convert string "END" to END constant
        if isinstance(node_config["next"], str) and node_config["next"] == "END":
            node_config["next"] = END
        elif isinstance(node_config["next"], dict):
            if node_config["next"].get("then") == "END":
                node_config["next"]["then"] = END
            if node_config["next"].get("else") == "END":
                node_config["next"]["else"] = END

        _validate_node_transitions(node_name, node_config["next"])


def _validate_prompt_node(node_name: str, config: Dict) -> None:
    """Validate prompt node specific configuration.
    
    Args:
        node_name: Name of the node
        config: Node configuration dictionary
        
    Raises:
        ValueError: If prompt node configuration is invalid
    """
    # Check required template field
    if "template" not in config:
        raise ValueError(f"Prompt node '{node_name}' missing 'template' field")

    # Validate optional image_keys field
    if "image_keys" in config and not isinstance(config["image_keys"], list):
        raise ValueError(f"Prompt node '{node_name}' image_keys must be a list")

    # Validate sink field if present
    if "sink" in config:
        if isinstance(config["sink"], str):
            config["sink"] = [config["sink"]]  # Convert single string to list
        elif not isinstance(config["sink"], list):
            raise ValueError(f"Prompt node '{node_name}' sink must be a string or list")

        # Validate each sink field name
        for sink in config["sink"]:
            if not isinstance(sink, str):
                raise ValueError(
                    f"Prompt node '{node_name}' sink values must be strings"
                )


def _validate_condition_expr(expr: str) -> bool:
    """Validate a conditional expression for security and correctness.
    
    Checks:
    - Python syntax validity
    - Allowed operations and functions
    - Security constraints
    
    Args:
        expr: Condition expression string
        
    Returns:
        bool: True if expression is valid
        
    Raises:
        ValueError: If expression is invalid or contains forbidden operations
    """
    import ast

    try:
        tree = ast.parse(expr, mode="eval")
        allowed_ops = (
            # Core expression nodes
            ast.Expression,  # Root node for eval mode
            ast.Name,  # Variable names
            ast.Constant,  # Literal values
            ast.List,  # List literals
            ast.Dict,  # Dictionary literals
            # Array/Dict access
            ast.Subscript,  # For array[index] or dict[key]
            ast.Index,  # For simple indexing
            ast.Slice,  # For slice operations
            # Comparison operators
            ast.Compare,
            ast.Eq,  # ==
            ast.NotEq,  # !=
            ast.Lt,  # <
            ast.LtE,  # <=
            ast.Gt,  # >
            ast.GtE,  # >=
            # Unary operators
            ast.UnaryOp,
            ast.Is,  # is
            ast.IsNot,  # is not
            ast.In,  # in
            ast.NotIn,  # not in
            # Boolean operators
            ast.BoolOp,
            ast.And,  # and
            ast.Or,  # or
            ast.Not,  # not
            # Function calls
            ast.Call,
            # Additional nodes for comprehensions
            ast.ListComp,  # List comprehensions
            ast.SetComp,  # Set comprehensions
            ast.DictComp,  # Dict comprehensions
            ast.GeneratorExp,  # Generator expressions
            ast.comprehension,  # The 'for' part of comprehensions
        )
        allowed_funcs = {
            "len",
            "upper",
            "lower",
            "str",
            "int",
            "float",
            "bool",
            "list",
            "dict",
            "all",
            "any",
            "filter",
            "map",
            "sum",
            "max",
            "min",
        }

        # Walk AST and validate each node
        for node in ast.walk(tree):
            # Skip context attributes
            if isinstance(node, (ast.Load, ast.Store)):
                continue

            if not isinstance(node, allowed_ops):
                raise ValueError(
                    f"Invalid operation in condition: {type(node).__name__}"
                )
            # Check function calls
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id not in allowed_funcs:
                        raise ValueError(
                            f"Function not allowed in condition: {node.func.id}"
                        )
                else:
                    raise ValueError("Only simple function calls are allowed")

        return True
    except SyntaxError as e:
        raise ValueError(f"Invalid Python syntax in condition: {str(e)}")
    except Exception as e:
        raise ValueError(f"Invalid condition expression: {str(e)}")


def _validate_node_transitions(node_name: str, next_config: Union[str, Dict]) -> None:
    """Validate node transition configuration.
    
    Checks transition configuration for both simple and conditional transitions.
    
    Args:
        node_name: Name of the node being validated
        next_config: Transition configuration (string for simple, dict for conditional)
        
    Raises:
        ValueError: If transition configuration is invalid
    """
    if isinstance(next_config, dict):
        # Validate conditional transition structure
        if "condition" not in next_config:
            raise ValueError(
                f"Conditional transition in node '{node_name}' missing 'condition'"
            )
        if "then" not in next_config or "else" not in next_config:
            raise ValueError(
                f"Conditional transition in node '{node_name}' missing then/else paths"
            )

        # Validate condition expression
        try:
            _validate_condition_expr(next_config["condition"])
        except ValueError as e:
            raise ValueError(f"Invalid condition in node '{node_name}': {str(e)}")


def _validate_state_definitions(state_defs: List, state_registry: Dict) -> None:
    """Validate state definitions in template.
    
    Supports both string references to registered states and tuple definitions.
    
    Args:
        state_defs: List of state definitions
        state_registry: Dictionary of available state types
        
    Raises:
        ValueError: If state definitions are invalid
    """
    for state_def in state_defs:
        if isinstance(state_def, str):
            # Validate reference to registered state
            if state_def not in state_registry:
                raise ValueError(f"Unknown state type: {state_def}")
        elif isinstance(state_def, list) and len(state_def) == 2:
            # Validate (name, type) tuple format
            name, type_str = state_def
            if not isinstance(name, str):
                raise ValueError(f"State name must be a string: {name}")
            try:
                _resolve_state_type(type_str)
            except ValueError:
                raise ValueError(f"Cannot resolve state type: {type_str}")
        else:
            raise ValueError(f"Invalid state definition format: {state_def}")


def _safe_read_template(template_path: str, node_registry: Dict, state_registry: Dict):
    """Safely load and perform initial validation of workflow template.
    
    Performs basic structural validation before any variable interpolation.
    
    Args:
        template_path: Path to YAML template file
        node_registry: Dictionary of available node types
        state_registry: Dictionary of available state types
        
    Returns:
        Dict: Loaded template dictionary
        
    Raises:
        ValueError: If template cannot be loaded or basic validation fails
    """
    # Load template
    try:
        with open(template_path, "r") as f:
            template = yaml.safe_load(f)
    except Exception as e:
        raise ValueError(f"Failed to load template: {str(e)}")

    # Check for required fields without validating their content yet
    required_fields = ["name", "state_defs", "nodes", "entry_point"]
    missing_fields = [field for field in required_fields if field not in template]
    if missing_fields:
        raise ValueError(f"Template missing required fields: {missing_fields}")

    # Basic type checking that won't be affected by variable interpolation
    if not isinstance(template.get("state_defs", []), list):
        raise ValueError("Template 'state_defs' must be a list")
    if not isinstance(template.get("nodes", {}), dict):
        raise ValueError("Template 'nodes' must be a dictionary")
    if not isinstance(template.get("exit_commands", []), list):
        raise ValueError("Template 'exit_commands' must be a list")
    if not isinstance(template.get("intervene_before", []), list):
        raise ValueError("Template 'intervene_before' must be a list")

    # Validate node structure (but not content)
    for node_name, node_config in template["nodes"].items():
        if not isinstance(node_config, dict):
            raise ValueError(f"Node '{node_name}' configuration must be a dictionary")
        if "type" not in node_config:
            raise ValueError(f"Node '{node_name}' missing 'type' field")
        if "next" not in node_config:
            raise ValueError(f"Node '{node_name}' missing 'next' field")

    return template


def _eval_condition_expr(node, state, allowed_funcs, operators):
    """Evaluate a single AST node in a condition expression.
    
    Recursively evaluates AST nodes while enforcing security constraints.
    
    Args:
        node: AST node to evaluate
        state: Current workflow state
        allowed_funcs: Dictionary of allowed functions
        operators: Dictionary of allowed operators
        
    Returns:
        Any: Result of evaluating the node
        
    Raises:
        ValueError: If evaluation encounters forbidden operations
    """
    if isinstance(node, ast.BoolOp):
        values = [
            _eval_condition_expr(v, state, allowed_funcs, operators)
            for v in node.values
        ]
        return operators[type(node.op)](*values)
    elif isinstance(node, ast.UnaryOp):
        operand = _eval_condition_expr(node.operand, state, allowed_funcs, operators)
        return operators[type(node.op)](operand)
    elif isinstance(node, ast.Compare):
        left = _eval_condition_expr(node.left, state, allowed_funcs, operators)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval_condition_expr(comparator, state, allowed_funcs, operators)
            # Special handling for 'in' operator - swap operands
            if isinstance(op, (ast.In, ast.NotIn)):
                if not operators[type(op)](right, left):
                    return False
            else:
                if not operators[type(op)](left, right):
                    return False
            left = right
        return True
    elif isinstance(node, ast.Name):
        return state.get(node.id, False)
    elif isinstance(node, ast.Constant):
        return node.value
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only simple function calls are allowed")
        if node.func.id not in allowed_funcs:
            raise ValueError(f"Function not allowed: {node.func.id}")
        args = [
            _eval_condition_expr(arg, state, allowed_funcs, operators)
            for arg in node.args
        ]
        return allowed_funcs[node.func.id](*args)
    elif isinstance(node, ast.List):
        return [
            _eval_condition_expr(elt, state, allowed_funcs, operators)
            for elt in node.elts
        ]
    elif isinstance(node, ast.Dict):
        return {
            _eval_condition_expr(
                k, state, allowed_funcs, operators
            ): _eval_condition_expr(v, state, allowed_funcs, operators)
            for k, v in zip(node.keys, node.values)
        }
    elif isinstance(node, ast.Subscript):
        value = _eval_condition_expr(node.value, state, allowed_funcs, operators)
        if isinstance(node.slice, ast.Slice):
            # Handle slice operations
            lower = (
                _eval_condition_expr(node.slice.lower, state, allowed_funcs, operators)
                if node.slice.lower is not None
                else None
            )
            upper = (
                _eval_condition_expr(node.slice.upper, state, allowed_funcs, operators)
                if node.slice.upper is not None
                else None
            )
            step = (
                _eval_condition_expr(node.slice.step, state, allowed_funcs, operators)
                if node.slice.step is not None
                else None
            )
            return value[slice(lower, upper, step)]
        elif isinstance(node.slice, ast.Index):
            idx = _eval_condition_expr(
                node.slice.value, state, allowed_funcs, operators
            )
        else:
            idx = _eval_condition_expr(node.slice, state, allowed_funcs, operators)
        return value[idx]
    elif isinstance(node, (ast.Load, ast.Store)):
        return None
    else:
        raise ValueError(f"Unsupported expression: {ast.dump(node)}")


def _eval_condition(condition_expr: str, state: Dict) -> str:
    """Evaluate a condition expression against the current state"""
    operators = {
        ast.And: operator.and_,
        ast.Or: operator.or_,
        ast.Not: operator.not_,
        ast.Eq: operator.eq,
        ast.NotEq: operator.ne,
        ast.Lt: operator.lt,
        ast.LtE: operator.le,
        ast.Gt: operator.gt,
        ast.GtE: operator.ge,
        ast.Is: operator.is_,
        ast.IsNot: operator.is_not,
        ast.In: operator.contains,
        ast.NotIn: lambda x, y: not operator.contains(y, x),
    }

    allowed_funcs = {
        "len": len,
        "upper": str.upper,
        "lower": str.lower,
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "list": list,
        "dict": dict,
        "all": all,
        "any": any,
        "filter": filter,
        "map": map,
        "sum": sum,
        "max": max,
        "min": min,
    }

    try:
        # First validate the expression
        _validate_condition_expr(condition_expr)

        # If validation passes, evaluate it
        expr_ast = ast.parse(condition_expr, mode="eval")
        result = _eval_condition_expr(expr_ast.body, state, allowed_funcs, operators)
        return "true" if result else "false"
    except Exception as e:
        # Log the error but also re-raise it
        logger.error(f"Error evaluating condition '{condition_expr}': {str(e)}")
        raise ValueError(f"Invalid condition expression: {str(e)}")


def _interpolate_variables(template: Dict, kwargs: Dict) -> Dict:
    """Recursively interpolate variables in template with values from kwargs

    Args:
        template: Template dictionary containing ${var} placeholders
        kwargs: Dictionary of variable values

    Returns:
        Dict with interpolated values
    """

    def _interpolate_value(value):
        if isinstance(value, str):
            # Handle string interpolation
            import re

            pattern = r"\${([^}]+)}"
            matches = re.finditer(pattern, value)
            result = value

            for match in matches:
                var_name = match.group(1)
                if var_name not in kwargs:
                    raise ValueError(
                        f"Required variable '{var_name}' not found in kwargs"
                    )
                # Convert kwargs[var_name] to string for replacement
                replacement = str(kwargs[var_name])
                result = result.replace(f"${{{var_name}}}", replacement)

            return result
        elif isinstance(value, dict):
            return {k: _interpolate_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [_interpolate_value(v) for v in value]
        return value

    return _interpolate_value(template)


def load_workflow_from_template(
    template_path: str,
    node_registry: Optional[Dict[str, Node]] = prebuilt_nodes,
    state_registry: Optional[Dict[str, State]] = prebuilt_states,
    custom_nodes: Optional[Dict[str, Node]] = None,
    custom_states: Optional[Dict[str, State]] = None,
    **kwargs,
) -> Workflow:
    """Create a Workflow instance from a YAML template file.

    This function loads a workflow definition from a YAML template, validates its structure,
    and creates a dynamic Workflow subclass with the specified configuration.

    Args:
        template_path (str): Path to the YAML template file
        node_registry (Optional[Dict[str, Node]]): Registry of available node types. 
            Defaults to prebuilt_nodes.
        state_registry (Optional[Dict[str, State]]): Registry of available state types.
            Defaults to prebuilt_states.
        custom_nodes (Optional[Dict[str, Node]]): Additional custom node types to include.
            These will be merged with the node_registry.
        custom_states (Optional[Dict[str, State]]): Additional custom state types to include.
            These will be merged with the state_registry.
        **kwargs: Additional arguments passed to the Workflow constructor and used for
            template variable interpolation.

    Returns:
        Workflow: A new Workflow subclass instance configured according to the template.

    Raises:
        ValueError: If the template structure is invalid, required variables are missing,
            or node/state definitions are incorrect.
        FileNotFoundError: If the template file cannot be found.
        yaml.YAMLError: If the template file contains invalid YAML.

    Template Structure:
        Required fields:
        - name: Workflow name
        - state_defs: List of state definitions
        - nodes: Dictionary of node configurations
        - entry_point: Name of the starting node

        Optional fields:
        - llm: LLM model name (default: "gpt-4o")
        - vlm: VLM model name
        - exit_commands: List of commands that will exit the workflow
        - intervene_before: List of nodes that require human input
        - save_artifacts: Whether to save state artifacts
        - debug_mode: Enable debug logging
        - max_history: Maximum number of states to keep in history

    Example:
        ```yaml
        # workflow_template.yaml
        name: example_workflow
        state_defs:
          - messages: List[Dict[str, str]]
          - current_step: str
        nodes:
          start:
            type: prompt
            template: "Hello! How can I help?"
            next: process_input
          process_input:
            type: custom_node
            next:
              condition: "len(messages) > 5"
              then: END
              else: start
        entry_point: start
        ```

        ```python
        workflow = load_workflow_from_template(
            "workflow_template.yaml",
            custom_nodes={"custom_node": my_node_function}
        )
        result = workflow.run()
        ```
    """
    # Combine registries
    if custom_nodes:
        node_registry = {**node_registry, **custom_nodes}
    if custom_states:
        state_registry = {**state_registry, **custom_states}

    # Load and perform basic validation of template structure
    template = _safe_read_template(template_path, node_registry, state_registry)

    # Interpolate variables in template
    template = _interpolate_variables(template, kwargs)

    # Now perform full validation after interpolation
    _validate_template_structure(template)
    _validate_state_definitions(template["state_defs"], state_registry)
    _validate_nodes(template["nodes"], node_registry)

    # Validate entry point
    assert (
        template["entry_point"] in template["nodes"].keys()
    ), f"Entry point '{template['entry_point']}' not found in nodes"

    # Create dynamic workflow class
    class UserWorkflow(Workflow):
        def __init__(self_, **kwargs):
            # Store template before super().__init__
            self_.template = template

            # Process state definitions from template
            state_defs = process_state_definitions(
                template["state_defs"], state_registry
            )

            # Create kwargs dictionary prioritizing template values
            workflow_kwargs = {}

            # Define mappings of template keys to Workflow parameter names
            param_mappings = {
                "name": "name",
                "llm": "llm_name",
                "vlm": "vlm_name",
                "exit_commands": "exit_commands",
                "save_artifacts": "save_artifacts",
                "debug_mode": "debug_mode",
                "max_history": "max_history",
            }

            # First check template values
            for template_key, param_name in param_mappings.items():
                if template_key in template:
                    workflow_kwargs[param_name] = template[template_key]

            # Then update with provided kwargs, but only for params not set from template
            for param_name in param_mappings.values():
                if param_name in kwargs and param_name not in workflow_kwargs:
                    workflow_kwargs[param_name] = kwargs[param_name]

            # Set defaults for required parameters if not found in template or kwargs
            if "llm_name" not in workflow_kwargs:
                workflow_kwargs["llm_name"] = "gpt-4o"
            if "vlm_name" not in workflow_kwargs:
                workflow_kwargs["vlm_name"] = None

            # Add state_defs to kwargs
            workflow_kwargs["state_defs"] = state_defs

            # Add any remaining kwargs that weren't mapped
            remaining_kwargs = {
                k: v
                for k, v in kwargs.items()
                if k not in workflow_kwargs and k not in param_mappings.values()
            }
            workflow_kwargs.update(remaining_kwargs)

            # Initialize workflow with combined settings
            super().__init__(**workflow_kwargs)

        def create_workflow(self_):
            """Create the workflow graph structure from template configuration"""
            # Initialize the workflow graph with state schema
            self_.workflow = StateGraph(self_.state_schema)

            # Get template configuration
            nodes_config = template["nodes"]
            interrupt_before = template.get("intervene_before", [])

            # Track input nodes for validation
            input_nodes = set()

            # First pass: Create all nodes including input nodes
            for node_name, node_config in nodes_config.items():
                # If this node needs human input, create an input node first
                if node_name in interrupt_before:
                    input_node_name = f"{node_name}_input"
                    input_nodes.add(input_node_name)

                    def create_input_node():
                        def input_node(state):
                            # Placeholder node for human input
                            return state

                        return input_node

                    # Add input node
                    self_.workflow.add_node(input_node_name, create_input_node())

                # Create the actual node
                node_type = node_config["type"]

                # Handle different node types
                if node_type == "prompt":
                    node = Node(
                        name=node_name,
                        prompt_template=node_config["template"],
                        sink=node_config.get("sink", []),
                        sink_format=node_config.get("format"),
                        image_keys=node_config.get("image_keys", []),
                    )
                    node_func = node.func
                else:
                    # Get node function from registry
                    node_func = node_registry[node_type]

                # Get the appropriate client
                client = (
                    self_.vlm_client
                    if "image_keys" in node_config
                    else self_.llm_client
                )

                # Create node function with config and client
                def create_node_function(func, config, client):
                    kwargs = config.get("kwargs", {})
                    return lambda state: func(state, client, **kwargs)

                # Add node to workflow
                self_.workflow.add_node(
                    node_name, create_node_function(node_func, node_config, client)
                )

            # Second pass: Add edges with proper routing through input nodes
            for node_name, node_config in nodes_config.items():
                next_config = node_config["next"]

                if isinstance(next_config, str):
                    # Handle simple edges
                    target = next_config
                    if target == "END":
                        target = END
                    elif target in interrupt_before:
                        # Route to the input node instead of the target
                        target = f"{target}_input"

                    # Add edge from input node if it exists
                    if node_name in interrupt_before:
                        input_node = f"{node_name}_input"
                        self_.workflow.add_edge(input_node, node_name)

                    # Add edge from actual node to target
                    self_.workflow.add_edge(node_name, target)

                elif isinstance(next_config, dict):
                    # Handle conditional edges
                    condition_expr = next_config["condition"]
                    then_target = next_config["then"]
                    else_target = next_config["else"]

                    # Convert "END" to END constant and route through input nodes
                    if then_target == "END":
                        then_target = END
                    elif then_target in interrupt_before:
                        then_target = f"{then_target}_input"

                    if else_target == "END":
                        else_target = END
                    elif else_target in interrupt_before:
                        else_target = f"{else_target}_input"

                    # Add edge from input node if it exists
                    if node_name in interrupt_before:
                        input_node = f"{node_name}_input"
                        self_.workflow.add_edge(input_node, node_name)

                    def make_condition(expr):
                        return lambda state: _eval_condition(expr, state)

                    self_.workflow.add_conditional_edges(
                        node_name,
                        make_condition(condition_expr),
                        {
                            "true": then_target,
                            "false": else_target,
                        },
                    )

            # Set entry point, routing through input node if necessary
            entry_point = self_.template["entry_point"]
            if entry_point in interrupt_before:
                entry_point = f"{entry_point}_input"
            self_.workflow.set_entry_point(entry_point)

            # Compile workflow with interrupt configuration
            self_.graph = self_.workflow.compile(
                checkpointer=MemorySaver(), interrupt_before=list(input_nodes)
            )
    return UserWorkflow(**kwargs)
