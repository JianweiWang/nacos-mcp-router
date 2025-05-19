#-*- coding: utf-8 -*-

import asyncio
import json
import os
from typing import Optional

import anyio
from mcp import types
from mcp.client.stdio import get_default_environment
from mcp.server import Server

from .logger import NacosMcpRouteLogger
from .mcp_manager import McpUpdater
from .nacos_http_client import NacosHttpClient
from .router_types import ChromaDb
from .router_types import CustomServer


router_logger = NacosMcpRouteLogger.get_logger()
mcp_servers_dict = {}
nacos_http_client: Optional[NacosHttpClient] = None
mcp_server: Optional[CustomServer] = None
tools: Optional[list[types.Tool]] = None
work_mode = os.getenv("MODE", "router")

def init_proxy() -> int:
  asyncio.run(init())

  app = Server("nacos_mcp_router")


  @app.call_tool()
  async def call_tool(
          name: str, arguments: dict
  ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    router_logger.info(f"calling tool: {name}, arguments: {arguments}")
    return await mcp_server.execute_tool(tool_name=name, arguments=arguments)
  @app.list_tools()
  async def list_tools() -> list[types.Tool]:
    return tools

  transport_type = os.getenv("TRANSPORT_TYPE", "stdio")
  match transport_type:
    case "stdio":
      from mcp.server.stdio import stdio_server

      async def arun():
        async with stdio_server() as streams:
          await app.run(
            streams[0], streams[1], app.create_initialization_options()
          )

      anyio.run(arun)
      
      return 0
    case "sse":
      from mcp.server.sse import SseServerTransport
      from starlette.applications import Starlette
      from starlette.responses import Response
      from starlette.routing import Mount, Route

      sse_transport = SseServerTransport("/messages/")
      sse_port = int(os.getenv("PORT", "8000"))
      async def handle_sse(request):
          async with sse_transport.connect_sse(
              request.scope, request.receive, request._send
          ) as streams:
              await app.run(
                  streams[0], streams[1], app.create_initialization_options()
              )
          return Response()

      starlette_app = Starlette(
          debug=True,
          routes=[
              Route("/sse", endpoint=handle_sse, methods=["GET"]),
              Mount("/messages/", app=sse_transport.handle_post_message),
          ],
      )

      import uvicorn

      uvicorn.run(starlette_app, host="0.0.0.0", port=sse_port)
      return 0
    case "streamable_http":
      streamable_port = int(os.getenv("PORT", "8000"))
      from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
      from mcp.server.auth import json_response
      session_manager = StreamableHTTPSessionManager(
        app=app,
        event_store=None,
        json_response=False,
        stateless=True,
      )
      from starlette.types import Scope
      from starlette.types import Receive
      from starlette.types import Send
      import contextlib
      from collections.abc import AsyncIterator
      from starlette.routing import Mount

      async def handle_streamable_http(
        scope: Scope, receive: Receive, send: Send
      ) -> None:
        await session_manager.handle_request(scope, receive, send)

      from starlette.applications import Starlette
      @contextlib.asynccontextmanager
      async def lifespan(app: Starlette) -> AsyncIterator[None]:
        """Context manager for session manager."""
        async with session_manager.run(): 
          try:
            yield
          finally:
            router_logger.info("Application shutting down...")
      starlette_app = Starlette(
        debug=True,
        routes=[
            Mount("/mcp", app=handle_streamable_http),
        ],
        lifespan=lifespan,
      )
      import uvicorn
      uvicorn.run(starlette_app, host="0.0.0.0", port=streamable_port)
      return 0
    case _:
      router_logger.error("unknown transport type: " + transport_type)
      return 1

def init_proxy() -> int:
  router_logger.info("init proxy")
  mcp_config = os.getenv("MCP_CONFIG", "")
  if mcp_config == "":
    router_logger.error("MCP_CONFIG is not set")
    return 1
  mcp_config = json.loads(mcp_config)
  router_logger.info("mcp_config: " + str(mcp_config))
  
  return 0

def main() -> int:
  if work_mode == "router":
    return init_router()
  elif work_mode == "proxy":
    return init_proxy()
  else:
    router_logger.error("unknown work mode: " + work_mode)
    return 1


async def init() -> int:
  global mcp_server, nacos_http_client, tools

  nacos_addr = os.getenv("NACOS_ADDR","127.0.0.1:8848")
  nacos_user_name = os.getenv("NACOS_USERNAME","nacos")
  nacos_password = os.getenv("NACOS_PASSWORD","")
  nacos_http_client = NacosHttpClient(nacosAddr=nacos_addr
                                        if nacos_addr != ""
                                        else "127.0.0.1:8848",

                                      userName=nacos_user_name
                                        if nacos_user_name != ""
                                        else "nacos",

                                      passwd=nacos_password)
  mcp_server_name = os.getenv("MCP_SERVER_NAME", "")
  mcp_server_config = os.getenv("MCP_SERVER_CONFIG", "")

  if mcp_server_name == "" or mcp_server_config == "":
    router_logger.error("MCP_SERVER_NAME or MCP_SERVER_CONFIG is not set")
  config = json.loads(mcp_server_config)
  mcp_server = CustomServer(name=mcp_server_name,config=config)
  await mcp_server.wait_for_initialization()
  if not mcp_server.healthy():
    router_logger.error("failed to init mcp server")
    return 1
  tools = await mcp_server.list_tools()




