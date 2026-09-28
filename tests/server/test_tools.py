def test_list_tools(client):
    response = client.get("/v1/tools")
    assert response.status_code == 200
    data = response.json()
    assert "tools" in data

    tools = data["tools"]
    assert len(tools) == 3

    names = {t["name"] for t in tools}
    assert names == {"write_file", "async_write", "read_file"}

    # Spot check one
    write_tool = next(t for t in tools if t["name"] == "write_file")
    assert write_tool["kind"] == "filesystem"
    assert write_tool["mutating"] is True
    assert write_tool["description"] == "Write a file"
    # Ensure no internal handlers are exposed
    assert "handler" not in write_tool
