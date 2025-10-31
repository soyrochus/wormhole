Extend the current OpenAI provider so it can also work with Azure OpenAI. So NO need to select a different provider in this case. 

The determinator to choose either connection to OpenAI or Azure OpenAI should be 
the env variable LLM_PROVIDER. These could contain the values "openai" or "azure_openai" 

if azure_open_ai then the following  envioronment values should be used
DO NOT HARD CODE THE EXAMPKE VALUES

AZURE_OPENAI_API_KEY=example-key
AZURE_OPENAI_ENDPOINT=https://corpus-oai-we-001.openai.azure.com
AZURE_OPENAI_API_VERSION=2024-12-01-preview
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o
AZURE_OPENAI_EMBEDDING_MODEL=text-embedding-ada-002




