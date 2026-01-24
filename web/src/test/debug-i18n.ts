
import enUS from '../locales/en-US.json';

const t = (key: string) => {
    const keys = key.split('.');
    let value: any = (enUS as any).default || enUS;
    for (const k of keys) {
        value = value?.[k];
    }
    return value || key;
};

console.log('project.graph.entities.filter.empty ->', t('project.graph.entities.filter.empty'));
console.log('project.graph.node_detail.tenant ->', t('project.graph.node_detail.tenant'));

const root: any = (enUS as any).default || enUS;
console.log('Root keys:', Object.keys(root).join(', '));
if (root.project) {
    console.log('Project keys:', Object.keys(root.project).join(', '));
    if (root.project.graph) {
        console.log('Project.Graph keys:', Object.keys(root.project.graph).join(', '));
    }
    if (root.project.schema && root.project.schema.graph) {
        console.log('Project.Schema.Graph keys:', Object.keys(root.project.schema.graph).join(', '));
    }
}
