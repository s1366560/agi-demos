import types


# Provide placeholders so unittest.mock.patch can target these attributes
async def acompletion(*args, **kwargs):
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message={"content": ""})])


async def aembedding(*args, **kwargs):
    return types.SimpleNamespace(data=[types.SimpleNamespace(embedding=[0.0])])
