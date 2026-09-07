#!/bin/bash
echo "==== exception around 19:35-19:36 ===="
docker logs --since 15m kirara-qq-bot 2>&1 | grep -aA 25 'Task exception was never retrieved' | head -80
echo "==== send_message / OneBot errors ===="
docker logs --since 30m kirara-qq-bot 2>&1 | grep -aE 'Error in send_message|send_group|Failed to send|OneBot|empty|content' | grep -v WebServer | grep -v DEBUG | tail -40
echo "==== converter / empty ===="
docker logs --since 15m kirara-qq-bot 2>&1 | grep -aE 'ChatResponse|SendIM|message_elements|llm_chat' | tail -20
