import type React from "react";
import { useEffect, useState } from "react";

import { SearchOutlined } from "@ant-design/icons";
import { Button, Input, Space, Table, Tag, Typography } from "antd";
import { useShallow } from "zustand/react/shallow";

import { useProviderStore } from "@/stores/provider";

import { PROVIDERS } from "@/constants/providers";

import type { ModelCatalogEntry } from "@/types/memory";

const { Text } = Typography;

export interface ModelCatalogBrowserProps {
	onSelect?: (model: ModelCatalogEntry) => void;
	selectedModel?: string;
	filterProvider?: string;
}

export const ModelCatalogBrowser: React.FC<ModelCatalogBrowserProps> = ({
	onSelect,
	selectedModel,
	filterProvider,
}) => {
	const { catalogLoading, modelSearchResults } = useProviderStore(
		useShallow((s) => ({
			catalogLoading: s.catalogLoading,
			modelSearchResults: s.modelSearchResults,
		})),
	);

	const { fetchModelCatalog, searchModels } = useProviderStore(
		useShallow((s) => ({
			fetchModelCatalog: s.fetchModelCatalog,
			searchModels: s.searchModels,
		})),
	);

	const [localSearch, setLocalSearch] = useState("");

	const [activeFilters, setActiveFilters] = useState<Record<string, boolean>>({
		vision: false,
		reasoning: false,
		tools: false,
		temp: false,
		seed: false,
		json: false,
		open: false,
	});

	const toggleFilter = (key: string, checked: boolean) => {
		setActiveFilters((prev) => ({ ...prev, [key]: checked }));
	};

	const filteredResults = modelSearchResults.filter((model) => {
		if (activeFilters.vision && !model.supports_attachment)
			return false;
		if (activeFilters.reasoning && !model.reasoning) return false;
		if (activeFilters.tools && !model.supports_tool_call) return false;
		if (activeFilters.temp && !model.supports_temperature) return false;
		if (activeFilters.seed && model.supports_seed !== true) return false;
		if (activeFilters.json && model.supports_response_format !== true)
			return false;
		if (activeFilters.open && !model.open_weights) return false;
		return true;
	});

	const filterTags = [
		{ key: "vision", label: "Vision" },
		{ key: "reasoning", label: "Reasoning" },
		{ key: "tools", label: "Tools" },
		{ key: "temp", label: "Temp" },
		{ key: "seed", label: "Seed" },
		{ key: "json", label: "JSON" },
		{ key: "open", label: "Open" },
	];

	useEffect(() => {
		fetchModelCatalog(filterProvider);
	}, [fetchModelCatalog, filterProvider]);

	const handleSearch = (e: React.ChangeEvent<HTMLInputElement>) => {
		const value = e.target.value;
		setLocalSearch(value);
		searchModels(value);
	};

	const getProviderIcon = (providerValue: string) => {
		const meta = PROVIDERS.find((p) => p.value === providerValue);
		return meta ? meta.icon : "🤖";
	};

	const columns = [
		{
			title: "Model",
			dataIndex: "name",
			key: "name",
			width: 220,
			render: (text: string, record: ModelCatalogEntry) => (
				<Space direction="vertical" size={0}>
					<Text strong>
						{record.provider && (
							<span className="mr-2" role="img" aria-label="provider">
								{getProviderIcon(record.provider)}
							</span>
						)}
						{text}
					</Text>
					{record.provider && (
						<Text type="secondary" className="text-xs">
							{record.provider}
						</Text>
					)}
				</Space>
			),
		},
		{
			title: "Context",
			dataIndex: "context_length",
			key: "context_length",
			width: 100,
			sorter: (a: ModelCatalogEntry, b: ModelCatalogEntry) =>
				a.context_length - b.context_length,
			render: (val: number) => (
				<Text>
					{val >= 1000000
						? `${(val / 1000000).toFixed(1)}M`
						: `${(val / 1000).toFixed(0)}k`}
				</Text>
			),
		},
		{
			title: "Max Output",
			dataIndex: "max_output_tokens",
			key: "max_output_tokens",
			width: 110,
			sorter: (a: ModelCatalogEntry, b: ModelCatalogEntry) =>
				a.max_output_tokens - b.max_output_tokens,
			render: (val: number) => (
				<Text>
					{val >= 1000000
						? `${(val / 1000000).toFixed(1)}M`
						: `${(val / 1000).toFixed(0)}k`}
				</Text>
			),
		},
		{
			title: "Cost ($/1M)",
			key: "cost",
			width: 120,
			render: (_: unknown, record: ModelCatalogEntry) => {
				const inCost = record.input_cost_per_1m;
				const outCost = record.output_cost_per_1m;
				if (inCost == null && outCost == null)
					return <Text type="secondary">-</Text>;
				return (
					<Space direction="vertical" size={0}>
						<Text className="text-xs">In: ${inCost?.toFixed(2) ?? "-"}</Text>
						<Text className="text-xs">Out: ${outCost?.toFixed(2) ?? "-"}</Text>
					</Space>
				);
			},
		},
		{
			title: "Features",
			key: "features",
			width: 240,
			render: (_: unknown, record: ModelCatalogEntry) => (
				<Space direction="vertical" size={4}>
					<Space size={[0, 4]} wrap>
						{record.reasoning && <Tag color="gold">Reasoning</Tag>}
						{record.supports_tool_call && (
							<Tag color="green">Tools</Tag>
						)}
						{record.supports_attachment && (
							<Tag color="purple">Vision</Tag>
						)}
						{record.supports_structured_output && (
							<Tag color="cyan">Structured</Tag>
						)}
						{record.open_weights && <Tag color="orange">Open</Tag>}
					</Space>
					<Space size={[0, 4]} wrap>
						{record.supports_temperature && <Tag>Temp</Tag>}
						{record.supports_top_p === true && <Tag>TopP</Tag>}
						{record.supports_frequency_penalty === true && <Tag>FreqP</Tag>}
						{record.supports_presence_penalty === true && <Tag>PresP</Tag>}
						{record.supports_seed === true && <Tag color="volcano">Seed</Tag>}
						{record.supports_stop === true && <Tag>Stop</Tag>}
						{record.supports_response_format === true && (
							<Tag color="geekblue">JSON</Tag>
						)}
					</Space>
				</Space>
			),
		},
		{
			title: "Action",
			key: "action",
			width: 90,
			render: (_: unknown, record: ModelCatalogEntry) => {
				const isSelected = selectedModel === record.name;
				return (
					<Button
						type={isSelected ? "primary" : "default"}
						size="small"
						onClick={() => onSelect?.(record)}
					>
						{isSelected ? "Selected" : "Select"}
					</Button>
				);
			},
		},
	];

	return (
		<div className="flex flex-col gap-4">
			<Input
				placeholder="Search models by name, provider, or capability..."
				prefix={<SearchOutlined className="text-gray-400" />}
				value={localSearch}
				onChange={handleSearch}
				allowClear
			/>
			<div className="flex flex-wrap items-center gap-2 mb-2">
				<Text type="secondary" className="text-sm">
					Filters:
				</Text>
				{filterTags.map((tag) => (
					<Tag.CheckableTag
						key={tag.key}
						checked={activeFilters[tag.key]}
						onChange={(checked) => { toggleFilter(tag.key, checked); }}
					>
						{tag.label}
					</Tag.CheckableTag>
				))}
			</div>
			<Table
				dataSource={filteredResults}
				columns={columns}
				rowKey="name"
				loading={catalogLoading}
				pagination={{ pageSize: 8 }}
				size="small"
				scroll={{ x: 880 }}
			/>
		</div>
	);
};
