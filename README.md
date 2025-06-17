# LiteLLM Proxy for LM Studio Integrations
Implementation of an incomplete lm-studio API which proxies requests to other AI providers

This allows using remote LLM inference with tooling that has LM Studio integration. Integration with
upstream models is through the excellent [LiteLLM proxy](https://docs.litellm.ai/docs/simple_proxy) providing
access to a [wide array](https://docs.litellm.ai/docs/providers) of providers and models.

E.g. JetBrains AI-Assistant (used in PyCharm / Intellij etc.) supports remote models using the 
JetBrains AI service, or local models via LM-Studio or Ollama.

With this project, JetBrains AI-Assistant can make requests through a local-proxy to any remote 
models (including pay-per-token models).  This can be helpful if you've run out of JetBrains credits


# Requirements
 - python3.12

The included `start_lm_proxy.sh` script should create the needed venv and install dependencies. 

# Config
There are two things to configure.
1. Provide API Keys for any remote models you want to configure
   
 Edit `api-keys.config` adding any keys you need


2. Define which models you want to access
   
 Edit `litellm-config.yaml` to define any models. Check the format [here](https://docs.litellm.ai/docs/proxy/configs)


# Run the proxy
 ```bash   
     start_lm_proxy.sh   
 ```
You can check your proxy is working with this curl command (replace MODEL_NAME with a model_name property from 
your litellm_config.yaml)
```
curl -X POST \
  http://localhost:8001/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
        "model": "MODEL_NAME",
        "messages": [
          {
            "role": "user",
            "content": "Hello, how are you?"
          }
        ]
      }'
```

# Using the proxy from JetBrains Ai Assistant

To use the proxy from JetBrains AI Assistant, follow these steps:

Once the proxy is running...
1. Open your JetBrains IDE (e.g., PyCharm, Intellij).
2. Go to **Settings** > **Tools** > **AI Assistants** > **Models**.
3. Select **enable LM Studio**.
4. Fill in the **URL** with `http://localhost:8001`.
5. Click "Test Connection" and confirm a green tick appears.
6. OPTIONAL enable Offline Mode and configure local models to use for **Core Features** and **Instant Helpers**

You should now be able to use the proxy with your JetBrains AI Assistant.

**Troubleshooting**

If you encounter issues, check the proxy logs and the IDE logs for errors. You can also try running the proxy 
with verbose logging to get more detailed output.

