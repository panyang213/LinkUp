from django.urls import path

from .consumers import ChatConsumer
from .consumers_dm import DMConsumer

websocket_urlpatterns = [
    path("ws/chat/", ChatConsumer.as_asgi()),
    path("ws/dm/", DMConsumer.as_asgi()),
]
