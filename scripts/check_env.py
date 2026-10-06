import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pinecone import Pinecone

load_dotenv()
kw = dict(base_url=os.environ["LLM_SERVICE_URL"], api_key=os.environ["LLM_API_KEY"])

llm = ChatOpenAI(model=os.environ["LLM_MODEL"], **kw)
emb = OpenAIEmbeddings(model=os.environ["EMBEDDING_MODEL"], check_embedding_ctx_length=False, **kw)

print(llm.invoke("decí hola").content)
print(len(emb.embed_query("hola")))

idx = Pinecone(api_key=os.environ["PINECONE_API_KEY"]).Index(os.environ["PINECONE_INDEX_NAME"])
print(idx.describe_index_stats())