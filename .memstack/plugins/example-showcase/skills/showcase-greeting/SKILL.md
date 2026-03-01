---
name: showcase-greeting
description: A greeting skill that teaches the agent how to greet users in multiple languages.
trigger_patterns:
  - "greet"
  - "hello"
  - "hi"
  - "greeting"
  - "welcome"
tools:
  - showcase_echo
user_invocable: true
---

# Greeting Skill

Greet the user warmly in the appropriate language.

## Guidelines

- Detect the user's language from their message
- Respond with a culturally appropriate greeting
- Keep greetings concise (1-2 sentences)
- If language is ambiguous, default to the project's primary language

## Examples

| User Says | Response |
|-----------|----------|
| "Hello" | "Hello! How can I help you today?" |
| "Bonjour" | "Bonjour! Comment puis-je vous aider?" |
| "Hola" | "Hola! Como puedo ayudarte hoy?" |
| "Nihao" | "Nihao! Wo neng wei ni zuo shenme?" |
