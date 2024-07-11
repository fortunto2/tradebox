import time
from typing import Dict

import requests
import streamlit as st
import uuid6
import extra_streamlit_components as stx

from core.schemas.sdxl_styles import SDXLStyle
from core.schemas.txt2video import Text2VideoConfig

# fastapi endpoint
API_URL = st.secrets.get("SUPERDUPERAI_HOST")
API_URL_EXT = st.secrets.get("SUPERDUPERAI_HOST_EXTERNAL")
if API_URL_EXT is None:
    API_URL_EXT = API_URL
print(API_URL)
print(API_URL_EXT)

if "headers" not in st.session_state:
    st.session_state["headers"] = None

token = None
unique_key = f"get_all_{time.time()}"  # Generate a unique key


# Cache the cookie manager resource
@st.cache_resource(experimental_allow_widgets=True)
def get_manager():
    # Your existing code
    return stx.CookieManager()


def logout():
    cookie_manager = get_manager()
    cookie_manager.delete("token")
    st.session_state.clear()
    st.rerun()


def logout_btn():
    st.button("Logout", on_click=logout)


def get_header():
    cookie_manager = get_manager()
    cookie_manager.get_all(key=unique_key)
    start_time = time.time()
    timeout = 0.01  # Preset timeout time
    while True:
        # if 'cookies' not in st.session_state:
        st.session_state['token'] = cookie_manager.get("token")

        if time.time() - start_time > timeout:
            st.warning("Operation timeout. Please refresh the page or check your network connection.")
            break  # If timed out, exit the loop directly
        else:
            if "token" not in st.session_state:
                continue
            break

    token = st.session_state.get('token')

    if token is None:
        token = st.text_input("Set API Token:", key="api_token")

        if token:
            st.session_state['token'] = token
    else:
        token = st.text_input("Api token:", value=token, key="api_token")

    st.session_state["headers"] = {"Authorization": f"Bearer {token}"} if token else None

    return st.session_state["headers"]


def get_current_user(headers=None):
    # from models.user import UserRead
    result = requests.get(f"{API_URL}/api/users/me/", headers=headers)
    # st.info(result.json())
    if result.status_code != 200:
        # st.error("Failed to fetch user from the API")
        return None
    return result.json()


# @st.cache_data
def get_project(chat_id, chat_type: str, current_user_uuid: uuid6.UUID) -> Dict:
    # from models.project import ProjectRead, ProjectListRead

    if chat_id is None:
        project = requests.post(
            f"{API_URL}/api/projects/",
            headers=st.session_state["headers"],
            json={
                "user_uuid": str(current_user_uuid),
                "template": False,
                "category": "chat",
                "type": chat_type,
            }
        )
    else:
        project = requests.get(f"{API_URL}/api/projects/{chat_id}", headers=st.session_state["headers"])

    if project.status_code != 200:
        st.error(f"Failed to make project: {chat_id} from the API")
        st.stop()

    return project.json()


def load_sidebar():
    headers = get_header()

    current_user = get_current_user(headers)

    if current_user is None and headers is not None:
        logout()

    # with st.expander("Settings"):

    if current_user:
        st.info(f"User: {current_user.get('email')}")
        logout_btn()
    else:
        url = f"{API_URL_EXT}/api/auth/login"
        st.markdown(f'''<a href="{url}" target="_self">Or Login</a>''', unsafe_allow_html=True)
        st.stop()
        return None

    params = st.experimental_get_query_params()
    chat_id = params.get("chat_id", [None])[0]  # Get the first value for "some_param", or None if it's not present

    # FIXME: Required to get chat type
    chat_type = "txt2video"
    project = get_project(chat_id, chat_type, current_user.get('uuid'))
    # st.write(project)

    try:
        # Get the current query parameters
        st.experimental_set_query_params(chat_id=project.get('uuid'))
    except Exception as e:
        st.warning(e)

    st.text_input(
        "project_id (chat_id):",
        project.get('uuid'),
        key="project_id",
    )

    return project


def load_video_settings(
        style: SDXLStyle,
        settings=None,
):
    if settings is None:
        settings = {}

    width = st.number_input("Video width:", value=settings.get('width', 1024))
    height = st.number_input("Video height:", value=settings.get('height', 1024))

    settings = Text2VideoConfig(
        text='',
        height=height,
        width=width,
        style=style.name,
    )

    return settings.model_dump()


import os
import time

import streamlit as st
import requests

from core import API_URL
from core.schemas.sdxl_styles import SDXLStyle
from core.schemas.txt2video import Text2VideoConfig


def make_video_from_text(text, project_uuid, settings: dict):
    settings["text"] = text

    dag_txt2video = requests.put(
        f"{API_URL}/api/dags/txt2video/{project_uuid}/",
        json=settings,
        headers=st.session_state["headers"],
        timeout=200
    )

    # st.info(dag_txt2video.content)

    dag_uuid = dag_txt2video.json().get('uuid')
    st.write(dag_uuid)

    return dag_uuid


def make_image_from_text(project_uuid, config: dict):
    dag_txt2img = requests.put(
        f"{API_URL}/api/dags/txt2img/{project_uuid}/",
        json=config,
        headers=st.session_state["headers"],
        timeout=200
    )

    dag_uuid = dag_txt2img.json().get('uuid')

    return dag_uuid


def make_video_from_timeline(project_uuid, config: dict):
    dag_timeline2video = requests.put(
        f"{API_URL}/api/dags/timeline2video/{project_uuid}/",
        json=config,
        headers=st.session_state["headers"],
        timeout=200
    )

    dag_uuid = dag_timeline2video.json().get('uuid')

    return dag_uuid


def select_image_style(style=None):
    # Initial setup
    enum_choices = [item.value.name.replace(" ", "_").replace("-", "_").upper() for item in SDXLStyle]
    index = enum_choices.index(style) if style else 0

    # Create the dropdown list in Streamlit
    choices = [item.value.name for item in SDXLStyle]
    selected = st.selectbox('Choose a style:', choices, index=index)

    # Retrieve the corresponding Enum member
    selected_enum_member = SDXLStyle[selected.replace(" ", "_").replace("-", "_").upper()]
    selected_prompt = selected_enum_member.value.prompt

    # Perform actions based on the selected Enum member
    st.write(f"{selected}: which corresponds to {selected_prompt}.")

    return selected_enum_member
