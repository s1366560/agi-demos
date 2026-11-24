import { Button, Flex, TextArea } from "@radix-ui/themes";

export function ClarificationForm({
  options,
  disabled,
  busy,
  allowCustom,
  answer,
  setAnswer,
  submit,
  placeholder,
  submitLabel,
}: {
  options: readonly {
    value: string;
    label: string;
    description?: string | undefined;
  }[];
  disabled: boolean;
  busy: boolean;
  allowCustom: boolean;
  answer: string;
  setAnswer(value: string): void;
  submit(value: string): void;
  placeholder: string;
  submitLabel: string;
}) {
  return (
    <div className="timeline-detail-block">
      {options.length ? (
        <Flex gap="2" wrap="wrap">
          {options.map((option) => (
            <Button
              size="1"
              variant="soft"
              disabled={disabled || busy}
              title={option.description}
              key={option.value}
              onClick={() => void submit(option.value)}
            >
              {option.label}
            </Button>
          ))}
        </Flex>
      ) : null}
      {allowCustom ? (
        <>
          <TextArea
            size="1"
            value={answer}
            disabled={disabled || busy}
            placeholder={placeholder}
            onChange={(event) => setAnswer(event.currentTarget.value)}
          />
          <Button
            size="1"
            disabled={disabled || busy || !answer.trim()}
            loading={busy}
            onClick={() => void submit(answer.trim())}
          >
            {submitLabel}
          </Button>
        </>
      ) : null}
    </div>
  );
}
