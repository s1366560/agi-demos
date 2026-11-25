import { createPortal } from 'react-dom';
import { useLayoutEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Mic, Phone } from 'lucide-react';

import { VoiceCallPanelView } from '../web/chat/VoiceCallPanelView';
import type { MenuEntry } from '../web/chat/ComposerPlusMenuView';
import type { Chat } from './useChat';

type Mode = 'dictation' | 'voice';
const initial = {
  connected: false,
  start: null as number | null,
  speaking: false,
  level: 0,
  muted: false,
  minimized: false,
  interim: '',
  final: '',
  response: '',
  streaming: false,
};
export function usePageVoiceControls(chat: Chat, available: boolean) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<Mode>();
  const [view, setView] = useState(initial);
  const active = useRef<AbortController | null>(null);
  const handle = useRef('');
  const cloudConversation =
    (chat.selectedRow?.execution_target ?? chat.target) === 'cloud' && chat.selected;
  useLayoutEffect(() => {
    setMode(undefined);
    setView(initial);
    return () => {
      active.current?.abort();
      active.current = null;
    };
  }, [cloudConversation, available]);
  const stop = () => {
    active.current?.abort();
    active.current = null;
    handle.current = '';
    setMode(undefined);
  };
  async function toggle(wanted: Mode) {
    if (active.current) {
      stop();
      return;
    }
    if (!available || !cloudConversation) return;
    const controller = new AbortController();
    active.current = controller;
    setMode(wanted);
    setView(initial);
    let prefix = chat.draft;
    try {
      await window.memstack.voice(wanted, cloudConversation, {
        signal: controller.signal,
        onEvent: (data) => {
          if (
            active.current !== controller ||
            controller.signal.aborted ||
            !data ||
            typeof data !== 'object'
          )
            return;
          const e = data as Record<string, unknown>;
          switch (e.type) {
            case 'handle':
              if (typeof e.id === 'string') handle.current = e.id;
              break;
            case 'connected':
              setView((v) => ({ ...v, connected: true, start: Date.now() }));
              break;
            case 'level':
              if (typeof e.level === 'number') {
                const level = Math.max(0, Math.min(1, e.level));
                setView((v) => ({ ...v, level }));
              }
              break;
            case 'asr_interim':
            case 'asr_final':
              if (typeof e.text === 'string') {
                const text = e.text;
                if (wanted === 'dictation') {
                  chat.setDraft(prefix + text);
                  if (e.type === 'asr_final') prefix += text;
                } else if (e.type === 'asr_interim') setView((v) => ({ ...v, interim: text }));
                else setView((v) => ({ ...v, final: text, interim: '', response: '' }));
              }
              break;
            case 'agent_token':
            case 'agent_complete':
              if (typeof e.content === 'string') {
                const content = e.content;
                setView((v) => ({
                  ...v,
                  response: e.type === 'agent_token' ? v.response + content : content,
                  streaming: e.type === 'agent_token',
                }));
              }
              break;
            case 'tts_start':
            case 'tts_end':
              setView((v) => ({ ...v, speaking: e.type === 'tts_start' }));
              break;
          }
        },
      });
    } catch (error) {
      if (!controller.signal.aborted) chat.report(error);
    } finally {
      if (active.current === controller) stop();
    }
  }
  const entries: MenuEntry[] = [
    {
      id: 'action-voice-input',
      section: 'actions',
      label:
        mode === 'dictation'
          ? t('agent.inputBar.stopVoice', 'Stop voice input')
          : t('agent.inputBar.startVoice', 'Voice input'),
      keywords: 'voice mic speech dictation',
      icon: <Mic size={16} />,
      disabled: !cloudConversation || mode === 'voice',
      active: mode === 'dictation',
      onSelect: () => void toggle('dictation'),
    },
    {
      id: 'action-voice-call',
      section: 'actions',
      label:
        mode === 'voice'
          ? t('agent.voiceCall.endCall', 'End call')
          : t('agent.inputBar.startVoiceCall', 'Start voice call'),
      keywords: 'voice call phone realtime',
      icon: <Phone size={16} />,
      disabled: !cloudConversation || mode === 'dictation',
      active: mode === 'voice',
      onSelect: () => void toggle('voice'),
    },
  ];
  const panel = mode === 'voice' && (
    <VoiceCallPanelView
      createPortal={createPortal}
      status={view.connected ? 'connected' : 'connecting'}
      callStartTime={view.start}
      error={null}
      isMuted={view.muted}
      aiSpeaking={view.speaking}
      isMinimized={view.minimized}
      asrFinalText={view.final}
      asrInterimText={view.interim}
      agentResponseText={view.response}
      isAgentStreaming={view.streaming}
      setMinimized={(minimized) => setView((v) => ({ ...v, minimized }))}
      storeToggleMute={() => {
        if (!handle.current || !active.current) return;
        const owner = active.current;
        void window.memstack
          .muteVoice(handle.current, !view.muted)
          .then(() => {
            if (active.current === owner) setView((v) => ({ ...v, muted: !view.muted }));
          })
          .catch((error) => {
            if (active.current === owner) chat.report(error);
          });
      }}
      handleEndCall={stop}
      waveform={
        <meter
          min={0}
          max={1}
          value={view.muted ? 0 : view.level}
          aria-label={t('agent.voiceCall.microphone', 'Microphone')}
        />
      }
    />
  );
  return { entries: available ? entries : [], panel };
}
