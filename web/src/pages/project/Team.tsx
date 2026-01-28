import React from 'react';
import { UserManager } from '@/components/tenant/UserManager';

export const Team: React.FC = () => {
    return (
        <div className="p-8">
            <UserManager context="project" />
        </div>
    );
};
