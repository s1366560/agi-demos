import { X, Zap } from 'lucide-react';
import {useTranslation} from 'react-i18next';
export function SelectedSkillChip({name,remove}:{name:string;remove:()=>void}) {
 const {t}=useTranslation();
 return (<div className="inline-flex max-w-full shrink-0 items-center gap-1 rounded border border-primary/20 bg-primary/5 px-2 py-1 text-xs font-medium text-primary dark:border-primary/30 dark:bg-primary/10">
                  <Zap size={12} />
                  <span className="max-w-[12rem] truncate">/{name}</span>
                  <button
                    type="button"
                    onClick={remove}
                    aria-label={t('agent.inputBar.removeSelectedSkill', {
                      name: name,
                      defaultValue: 'Remove /{{name}} skill',
                    })}
                    title={t('agent.inputBar.removeSelectedSkill', {
                      name: name,
                      defaultValue: 'Remove /{{name}} skill',
                    })}
                    className="-mr-0.5 rounded-md p-0.5 transition-colors duration-150 hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
                  >
                    <X size={10} />
                  </button>
                </div>);
}
