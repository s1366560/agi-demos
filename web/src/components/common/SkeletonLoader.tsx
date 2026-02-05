import React from 'react'

import { Skeleton , Card, Row, Col } from 'antd'

export interface SkeletonLoaderProps {
    type?: 'list' | 'card' | 'table' | 'form' | 'chat'
    count?: number
    rows?: number
}

/**
 * SkeletonLoader Component
 * Provides loading placeholders for better perceived performance
 *
 * @param type - Type of skeleton to display
 * @param count - Number of items to show (for list/card types)
 * @param rows - Number of rows (for table type)
 */
export const SkeletonLoader: React.FC<SkeletonLoaderProps> = ({
    type = 'list',
    count = 3,
    rows = 5,
}) => {
    switch (type) {
        case 'list':
            return (
                <div style={{ padding: '16px' }}>
                    {Array.from({ length: count }).map((_, i) => (
                        <div
                            key={i}
                            style={{
                                marginBottom: i < count - 1 ? '16px' : 0,
                                padding: '16px',
                                border: '1px solid #f0f0f0',
                                borderRadius: '8px',
                            }}
                        >
                            <Skeleton.Input active style={{ width: '60%', marginBottom: '12px' }} size="small" />
                            <Skeleton.Input active style={{ width: '100%', marginBottom: '8px' }} size="small" />
                            <Skeleton.Input active style={{ width: '80%' }} size="small" />
                        </div>
                    ))}
                </div>
            )

        case 'card':
            return (
                <Row gutter={[16, 16]} style={{ padding: '16px' }}>
                    {Array.from({ length: count }).map((_, i) => (
                        <Col xs={24} sm={12} md={8} lg={6} key={i}>
                            <Card>
                                <Skeleton.Image active style={{ width: '100%', height: 150, marginBottom: 16 }} />
                                <Skeleton.Input active style={{ width: '70%', marginBottom: 8 }} size="small" />
                                <Skeleton.Input active style={{ width: '100%', marginBottom: 8 }} size="small" />
                                <Skeleton.Input active style={{ width: '40%' }} size="small" />
                            </Card>
                        </Col>
                    ))}
                </Row>
            )

        case 'table':
            return (
                <div style={{ padding: '16px' }}>
                    {Array.from({ length: rows }).map((_, i) => (
                        <div
                            key={i}
                            style={{
                                display: 'flex',
                                gap: '16px',
                                marginBottom: '12px',
                                padding: '12px',
                                borderBottom: '1px solid #f0f0f0',
                            }}
                        >
                            <Skeleton.Input active style={{ width: '5%' }} size="small" />
                            <Skeleton.Input active style={{ width: '25%' }} size="small" />
                            <Skeleton.Input active style={{ width: '20%' }} size="small" />
                            <Skeleton.Input active style={{ width: '15%' }} size="small" />
                            <Skeleton.Input active style={{ width: '15%' }} size="small" />
                            <Skeleton.Input active style={{ width: '10%' }} size="small" />
                        </div>
                    ))}
                </div>
            )

        case 'form':
            return (
                <div style={{ padding: '24px', maxWidth: '600px' }}>
                    <Skeleton.Input active style={{ width: '40%', marginBottom: '24px', height: 32 }} />
                    {Array.from({ length: 4 }).map((_, i) => (
                        <div key={i} style={{ marginBottom: '24px' }}>
                            <Skeleton.Input active style={{ width: '20%', marginBottom: '8px' }} size="small" />
                            <Skeleton.Input active style={{ width: '100%', height: 40 }} />
                        </div>
                    ))}
                    <Skeleton.Button active style={{ width: 120, height: 40 }} />
                </div>
            )

        case 'chat':
            return (
                <div style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
                    {/* User message */}
                    <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                        <div
                            style={{
                                maxWidth: '70%',
                                padding: '12px 16px',
                                background: '#193db3',
                                borderRadius: '12px',
                            }}
                        >
                            <Skeleton.Input active style={{ width: 120, backgroundColor: 'rgba(255,255,255,0.2)' }} size="small" />
                        </div>
                    </div>
                    {/* Bot response */}
                    <div style={{ display: 'flex', justifyContent: 'flex-start' }}>
                        <div
                            style={{
                                maxWidth: '70%',
                                padding: '12px 16px',
                                background: '#f5f5f5',
                                borderRadius: '12px',
                            }}
                        >
                            <Skeleton.Input active style={{ width: 200, marginBottom: 8 }} size="small" />
                            <Skeleton.Input active style={{ width: 160, marginBottom: 8 }} size="small" />
                            <Skeleton.Input active style={{ width: 140 }} size="small" />
                        </div>
                    </div>
                    {/* Another user message */}
                    <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                        <div
                            style={{
                                maxWidth: '70%',
                                padding: '12px 16px',
                                background: '#193db3',
                                borderRadius: '12px',
                            }}
                        >
                            <Skeleton.Input active style={{ width: 80, backgroundColor: 'rgba(255,255,255,0.2)' }} size="small" />
                        </div>
                    </div>
                    {/* Loading indicator */}
                    <div style={{ display: 'flex', justifyContent: 'flex-start', alignItems: 'center', gap: '4px' }}>
                        <Skeleton.Avatar active size="small" />
                        <div style={{ display: 'flex', gap: '4px' }}>
                            {[0, 1, 2].map((i) => (
                                <div
                                    key={i}
                                    style={{
                                        width: '8px',
                                        height: '8px',
                                        borderRadius: '50%',
                                        background: '#d9d9d9',
                                        animation: 'pulse 1.4s ease-in-out infinite',
                                        animationDelay: `${i * 0.2}s`,
                                    }}
                                />
                            ))}
                        </div>
                    </div>
                </div>
            )

        default:
            return <Skeleton active />
    }
}

export default SkeletonLoader
