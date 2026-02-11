/**
 * OnboardingTour - First-time user walkthrough for the AI workspace.
 *
 * Shows a 5-step guided tour highlighting key features with spotlight
 * effects and floating tooltip cards. Pure CSS + React, no external libs.
 *
 * Persists completion state via localStorage key `memstack_onboarding_complete`.
 */

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';

import { useTranslation } from 'react-i18next';

interface OnboardingTourProps {
  onComplete: () => void;
}

interface TourStep {
  titleKey: string;
  titleFallback: string;
  descKey: string;
  descFallback: string;
  targetSelector: string | null;
}

interface TargetRect {
  top: number;
  left: number;
  width: number;
  height: number;
}

const TOUR_STEPS: TourStep[] = [
  {
    titleKey: 'agent.onboarding.welcome',
    titleFallback: 'Welcome to MemStack',
    descKey: 'agent.onboarding.welcomeDesc',
    descFallback: 'Your AI-powered workspace for analysis, coding, and automation.',
    targetSelector: null,
  },
  {
    titleKey: 'agent.onboarding.inputTip',
    titleFallback: 'Chat with your AI assistant',
    descKey: 'agent.onboarding.inputDesc',
    descFallback: 'Type messages naturally, or use / to access commands and tools.',
    targetSelector: '[data-tour="input-bar"]',
  },
  {
    titleKey: 'agent.onboarding.layoutTip',
    titleFallback: 'Multiple layout modes',
    descKey: 'agent.onboarding.layoutDesc',
    descFallback: 'Switch between Chat, Code, Desktop, Focus, and Canvas modes with Cmd+1-5.',
    targetSelector: '[data-tour="layout-selector"]',
  },
  {
    titleKey: 'agent.onboarding.templateTip',
    titleFallback: 'Quick-start templates',
    descKey: 'agent.onboarding.templateDesc',
    descFallback: 'Browse pre-built prompts for common tasks.',
    targetSelector: '[data-tour="prompt-templates"]',
  },
  {
    titleKey: 'agent.onboarding.searchTip',
    titleFallback: 'Search conversations',
    descKey: 'agent.onboarding.searchDesc',
    descFallback: 'Use Cmd+F to search within any conversation.',
    targetSelector: null,
  },
];

const CARD_WIDTH = 360;
const CARD_HEIGHT_EST = 180;
const SPOTLIGHT_PAD = 8;

function getTargetRect(selector: string | null): TargetRect | null {
  if (!selector) return null;
  const el = document.querySelector(selector);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return { top: r.top, left: r.left, width: r.width, height: r.height };
}

function computeCardPosition(
  rect: TargetRect | null,
): { top: number; left: number } {
  if (!rect) {
    return {
      top: Math.max(0, (window.innerHeight - CARD_HEIGHT_EST) / 2),
      left: Math.max(0, (window.innerWidth - CARD_WIDTH) / 2),
    };
  }

  const cx = rect.left + rect.width / 2;
  let left = cx - CARD_WIDTH / 2;
  left = Math.max(16, Math.min(left, window.innerWidth - CARD_WIDTH - 16));

  const spaceBelow = window.innerHeight - (rect.top + rect.height + SPOTLIGHT_PAD);
  if (spaceBelow >= CARD_HEIGHT_EST + 16) {
    return { top: rect.top + rect.height + SPOTLIGHT_PAD + 12, left };
  }
  return { top: Math.max(16, rect.top - SPOTLIGHT_PAD - CARD_HEIGHT_EST - 12), left };
}

export const OnboardingTour: React.FC<OnboardingTourProps> = ({ onComplete }) => {
  const { t } = useTranslation();
  const [step, setStep] = useState(0);
  const [targetRect, setTargetRect] = useState<TargetRect | null>(null);
  const [cardPos, setCardPos] = useState({ top: 0, left: 0 });
  const rafRef = useRef<number>(0);
  const reducedMotion =
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const currentStep = TOUR_STEPS[step];

  // Measure target element position on step change and window resize
  const measure = useCallback(() => {
    const rect = getTargetRect(currentStep.targetSelector);
    setTargetRect(rect);
    setCardPos(computeCardPosition(rect));
  }, [currentStep.targetSelector]);

  useEffect(() => {
    // Use rAF for initial measurement to avoid synchronous setState in effect
    const frameId = requestAnimationFrame(measure);
    const onResize = () => {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(measure);
    };
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      cancelAnimationFrame(rafRef.current);
      cancelAnimationFrame(frameId);
    };
  }, [measure]);

  const handleNext = useCallback(() => {
    if (step < TOUR_STEPS.length - 1) {
      setStep((s) => s + 1);
    } else {
      onComplete();
    }
  }, [step, onComplete]);

  const handleSkip = useCallback(() => {
    onComplete();
  }, [onComplete]);

  // Close on Escape
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onComplete();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onComplete]);

  const isLast = step === TOUR_STEPS.length - 1;
  const transition = reducedMotion ? 'none' : 'all 0.3s ease';

  const spotlightStyle = useMemo<React.CSSProperties | undefined>(() => {
    if (!targetRect) return undefined;
    return {
      position: 'absolute',
      top: targetRect.top - SPOTLIGHT_PAD,
      left: targetRect.left - SPOTLIGHT_PAD,
      width: targetRect.width + SPOTLIGHT_PAD * 2,
      height: targetRect.height + SPOTLIGHT_PAD * 2,
      borderRadius: 12,
      boxShadow: '0 0 0 9999px rgba(0,0,0,0.55)',
      pointerEvents: 'none' as const,
      transition,
      zIndex: 101,
    };
  }, [targetRect, transition]);

  const ofLabel = t('agent.onboarding.stepOf', 'of');

  return (
    <div
      className="fixed inset-0 z-[100]"
      role="dialog"
      aria-modal="true"
      aria-label="Onboarding tour"
    >
      {/* Backdrop - only when no spotlight target */}
      {!targetRect && (
        <div
          className="absolute inset-0 bg-black/55"
          style={{ transition }}
        />
      )}

      {/* Spotlight ring */}
      {targetRect && <div style={spotlightStyle} />}

      {/* Tooltip card */}
      <div
        className="absolute z-[102] w-[360px] rounded-xl bg-white dark:bg-slate-800 shadow-2xl border border-slate-200/80 dark:border-slate-700/80 p-5"
        style={{
          top: cardPos.top,
          left: cardPos.left,
          transition,
        }}
      >
        {/* Step indicator */}
        <div className="flex items-center gap-1.5 mb-3">
          {TOUR_STEPS.map((_, i) => (
            <div
              key={i}
              className={`h-1.5 rounded-full transition-all duration-200 ${
                i === step
                  ? 'w-6 bg-blue-500'
                  : i < step
                    ? 'w-1.5 bg-blue-300 dark:bg-blue-600'
                    : 'w-1.5 bg-slate-200 dark:bg-slate-600'
              }`}
            />
          ))}
          <span className="ml-auto text-xs text-slate-400 dark:text-slate-500 tabular-nums">
            {step + 1} {ofLabel} {TOUR_STEPS.length}
          </span>
        </div>

        {/* Content */}
        <h3 className="text-base font-semibold text-slate-800 dark:text-slate-100 mb-1.5">
          {t(currentStep.titleKey, currentStep.titleFallback)}
        </h3>
        <p className="text-sm text-slate-500 dark:text-slate-400 leading-relaxed mb-5">
          {t(currentStep.descKey, currentStep.descFallback)}
        </p>

        {/* Actions */}
        <div className="flex items-center justify-between">
          <button
            type="button"
            onClick={handleSkip}
            className="text-sm text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
          >
            {t('agent.onboarding.skip', 'Skip tour')}
          </button>
          <button
            type="button"
            onClick={handleNext}
            className="px-4 py-1.5 rounded-lg bg-blue-500 hover:bg-blue-600 text-white text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500/50"
          >
            {isLast
              ? t('agent.onboarding.done', 'Get started')
              : t('agent.onboarding.next', 'Next')}
          </button>
        </div>
      </div>
    </div>
  );
};
