"""agent.modules.inspection

CMDB-driven network device inspection. The runner uses
``ToolRuntimeClient.invoke("exec.run", …)`` (a canonical tool) so
credentials stay server-side — there is no separate password
loader, no parallel exec path.
"""
