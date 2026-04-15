from sqlalchemy.orm import Session
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from core.models import StoryLLMResponse, StoryNodeLLM
from core.prompts import STORY_PROMPT
from models.story import Story, StoryNode
from dotenv import load_dotenv

load_dotenv()


class StoryGenerator:
    @classmethod
    def _get_llm(cls):

        return ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0.8
        )

    @classmethod
    def generate_story(cls, db: Session, session_id: str, theme: str = "fantasy") -> Story:
        llm = cls._get_llm()
        story_parser = PydanticOutputParser(pydantic_object=StoryLLMResponse)

        prompt = ChatPromptTemplate.from_messages([
            ("system", STORY_PROMPT),
            ("human", f"Create the story with this theme: {theme}")
        ]).partial(format_instructions=story_parser.get_format_instructions())

        # 3. Use the chain syntax for better compatibility with output parsers
        chain = prompt | llm
        raw_response = chain.invoke({})

        # Gemini returns an AIMessage; we need the string content for the parser
        response_text = raw_response.content if hasattr(raw_response, "content") else raw_response

        story_structure = story_parser.parse(response_text)

        story_db = Story(title=story_structure.title, session_id=session_id)
        db.add(story_db)
        db.flush()

        # The rest of your logic remains the same
        root_node_data = story_structure.rootNode
        if isinstance(root_node_data, dict):
            root_node_data = StoryNodeLLM.model_validate(root_node_data)

        # Call your recursive processor here
        cls._process_story_node(db, story_db.id, root_node_data, is_root=True)

        db.commit()
        return story_db

    @classmethod
    def _process_story_node(cls, db: Session, story_id: int, node_data: StoryNodeLLM,
                            is_root: bool = False) -> StoryNode:
        # Keep your existing logic for processing nodes...
        node = StoryNode(
            story_id=story_id,
            content=getattr(node_data, "content", node_data.get("content") if isinstance(node_data, dict) else ""),
            is_root=is_root,
            is_ending=getattr(node_data, "isEnding", False),
            is_winning_ending=getattr(node_data, "isWinningEnding", False),
            options=[]
        )

        db.add(node)
        db.flush()

        if not node.is_ending and hasattr(node_data, "options") and node_data.options:
            options_list = []
            for option_data in node_data.options:
                next_node = option_data.nextNode
                if isinstance(next_node, dict):
                    next_node = StoryNodeLLM.model_validate(next_node)

                child_node = cls._process_story_node(db, story_id, next_node, False)
                options_list.append({"text": option_data.text, "node_id": child_node.id})

            node.options = options_list
        db.flush()
        return node
