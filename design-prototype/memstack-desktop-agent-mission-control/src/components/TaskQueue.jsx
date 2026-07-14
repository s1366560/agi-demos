import {
  ChevronDownIcon,
  CircleBackslashIcon,
  ClockIcon,
  CounterClockwiseClockIcon,
  DotsHorizontalIcon,
  ExclamationTriangleIcon,
  MagnifyingGlassIcon,
} from '@radix-ui/react-icons';

const groupConfig = [
  ['input', 'Needs input', ExclamationTriangleIcon],
  ['running', 'Running', CounterClockwiseClockIcon],
  ['ready', 'Ready to review', ClockIcon],
];

function TaskCard({ task, selected, onSelect, onInput }) {
  return (
    <article
      className={`task-card ${selected ? 'selected' : ''}`}
      onClick={() => onSelect(task.id)}
    >
      <button className="task-card-main" type="button">
        <span className={`status-dot ${task.status}`} />
        <span>
          <strong>{task.title}</strong>
          <small>{task.summary}</small>
          <em>{task.meta}</em>
        </span>
      </button>
      <button className="task-menu" type="button" aria-label={`More actions for ${task.title}`}>
        <DotsHorizontalIcon />
      </button>
      {task.status === 'input' && (
        <button className="inline-action" type="button" onClick={(event) => { event.stopPropagation(); onInput(task); }}>
          Provide input
        </button>
      )}
    </article>
  );
}

export function TaskQueue({ mode, tasks, selectedId, onSelect, onInput }) {
  return (
    <section className="task-queue" aria-label={`${mode} task queue`}>
      <header className="queue-header">
        <div>
          <span>{mode === 'work' ? 'MISSION CONTROL' : 'CODE SESSIONS'}</span>
          <h1>My Work</h1>
        </div>
        <button className="icon-button" type="button" aria-label="Task filters"><CircleBackslashIcon /></button>
      </header>

      <label className="queue-search">
        <MagnifyingGlassIcon />
        <input aria-label="Search tasks" placeholder="Search tasks" />
        <kbd>⌘ K</kbd>
      </label>

      <div className="queue-filters">
        <button className="active" type="button">All</button>
        <button type="button">Assigned to me</button>
        <button type="button">Recent</button>
      </div>

      <div className="queue-scroll">
        {groupConfig.map(([status, label, Icon]) => {
          const groupTasks = tasks.filter((task) => task.status === status);
          return (
            <section className="task-group" key={status}>
              <div className="task-group-title">
                <Icon />
                <span>{label}</span>
                <b>{groupTasks.length}</b>
                <ChevronDownIcon />
              </div>
              {groupTasks.map((task) => (
                <TaskCard
                  key={task.id}
                  task={task}
                  selected={selectedId === task.id}
                  onSelect={onSelect}
                  onInput={onInput}
                />
              ))}
            </section>
          );
        })}
      </div>
    </section>
  );
}
