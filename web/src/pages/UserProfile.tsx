import React, { useEffect, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { Building2, Calendar, Camera, CheckCircle, KeyRound, MapPin, X } from 'lucide-react';

import { formatDateOnly } from '@/utils/date';

import { authAPI } from '../services/api';
import { useAuthStore } from '../stores/auth';

import type { User, UserProfile as UserProfileType, UserUpdate } from '../types/memory';

type UserProfileFormData = UserUpdate & { email: string };
type ProfileSectionId = 'basic' | 'contact' | 'preferences' | 'security';

const DEFAULT_PROFILE: UserProfileType = {
  job_title: '',
  department: 'Engineering',
  bio: '',
  phone: '',
  location: '',
  timezone: 'Pacific Time (US & Canada)',
  avatar_url: '',
};

const profileSections: Array<{ id: ProfileSectionId; labelKey: string }> = [
  { id: 'basic', labelKey: 'user_profile.tabs.basic' },
  { id: 'contact', labelKey: 'user_profile.tabs.contact' },
  { id: 'preferences', labelKey: 'user_profile.tabs.preferences' },
  { id: 'security', labelKey: 'user_profile.tabs.security' },
];

const buildUserFormData = (user: User): UserProfileFormData => ({
  name: user.name,
  email: user.email,
  preferred_language:
    user.preferred_language ??
    (user.profile?.language === 'Chinese (Simplified)' ? 'zh-CN' : 'en-US'),
  profile: {
    ...DEFAULT_PROFILE,
    ...(user.profile ?? {}),
  },
});

export const UserProfile: React.FC = () => {
  const { i18n, t } = useTranslation();
  const { user, setUser } = useAuthStore();
  const avatarUrlInputRef = useRef<HTMLInputElement>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [showSuccess, setShowSuccess] = useState(false);
  const [activeSection, setActiveSection] = useState<ProfileSectionId>('basic');
  const [formData, setFormData] = useState<UserProfileFormData>({
    name: '',
    email: '',
    profile: DEFAULT_PROFILE,
  });

  useEffect(() => {
    if (user) {
      setFormData(buildUserFormData(user));
    }
  }, [user]);

  const handleSectionClick = (sectionId: ProfileSectionId) => {
    setActiveSection(sectionId);
    const section = document.getElementById(`profile-section-${sectionId}`);
    if (typeof section?.scrollIntoView === 'function') {
      section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  const focusAvatarUrlInput = () => {
    setActiveSection('basic');
    avatarUrlInputRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    avatarUrlInputRef.current?.focus();
  };

  const handleChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>
  ) => {
    const { name, value } = e.target;
    if (name === 'name' || name === 'email') {
      setFormData((prev) => ({ ...prev, [name]: value }));
    } else if (name === 'preferred_language') {
      setFormData((prev) => ({
        ...prev,
        preferred_language: value === 'zh-CN' ? 'zh-CN' : 'en-US',
      }));
    } else {
      setFormData((prev) => ({
        ...prev,
        profile: {
          ...(prev.profile ?? {}),
          [name]: value,
        },
      }));
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    try {
      // Create update data that matches UserUpdate interface
      const updateData = {
        name: formData.name,
        profile: formData.profile,
        preferred_language: formData.preferred_language,
      };
      const updatedUser = await authAPI.updateProfile(updateData);
      setUser(updatedUser);
      if (updatedUser.preferred_language) {
        void i18n.changeLanguage(updatedUser.preferred_language);
      }
      setShowSuccess(true);
      setTimeout(() => {
        setShowSuccess(false);
      }, 3000);
    } catch (error) {
      console.error('Failed to update profile:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleCancel = () => {
    if (user) {
      setFormData(buildUserFormData(user));
    }
  };

  if (!user) return <div className="p-8 text-center">{t('common.loading')}</div>;

  return (
    <div className="mx-auto w-full max-w-7xl p-4 sm:p-6 lg:p-8">
      {/* Page Heading */}
      <div className="mb-8 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-900 dark:text-white">
            {t('user_profile.title')}
          </h1>
          <p className="mt-2 text-slate-500 dark:text-slate-400">{t('user_profile.subtitle')}</p>
        </div>
        <div className="hidden sm:block">
          <span className="inline-flex items-center rounded-full bg-green-50 px-3 py-1 text-xs font-medium text-green-700 ring-1 ring-inset ring-green-600/20 dark:bg-green-900/30 dark:text-green-400">
            <span className="mr-1.5 h-1.5 w-1.5 rounded-full bg-green-600"></span>
            {t('user_profile.account_active')}
          </span>
        </div>
      </div>

      {/* Content Grid */}
      <div className="grid min-w-0 grid-cols-1 gap-6 lg:grid-cols-3 xl:gap-8">
        {/* Left Column: Summary Card */}
        <div className="lg:col-span-1">
          <div className="sticky top-24 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-700 dark:bg-surface-dark">
            <div className="relative h-32 bg-gradient-to-r from-primary/80 to-blue-600/80"></div>
            <div className="relative flex flex-col items-center px-6 pb-8">
              <div className="relative -mt-16 mb-4">
                <div className="h-32 w-32 overflow-hidden rounded-full border-4 border-white bg-white shadow-md dark:border-surface-dark">
                  <img
                    alt={user.name}
                    className="h-full w-full object-cover"
                    src={
                      formData.profile?.avatar_url ||
                      `https://ui-avatars.com/api/?name=${encodeURIComponent(user.name)}&background=random`
                    }
                  />
                </div>
                <button
                  type="button"
                  aria-label={t('user_profile.avatar.change', 'Change avatar')}
                  title={t('user_profile.avatar.change', 'Change avatar')}
                  className="absolute bottom-1 right-1 flex h-8 w-8 cursor-pointer items-center justify-center rounded-full bg-primary text-white shadow-lg transition-transform hover:scale-110 hover:bg-primary-dark"
                  onClick={focusAvatarUrlInput}
                >
                  <Camera size={14} />
                </button>
              </div>
              <h2 className="text-xl font-bold text-slate-900 dark:text-white">{user.name}</h2>
              <p className="text-sm font-medium text-slate-500 dark:text-slate-400">
                {formData.profile?.job_title || t('user_profile.no_job_title')}
              </p>
              <div className="mt-4 flex w-full flex-col gap-2 border-t border-slate-200 py-4 dark:border-slate-700">
                <div className="flex items-center gap-3 text-sm text-slate-500 dark:text-slate-400">
                  <Building2 size={18} />
                  <span>{formData.profile?.department || t('user_profile.no_department')}</span>
                </div>
                <div className="flex items-center gap-3 text-sm text-slate-500 dark:text-slate-400">
                  <MapPin size={18} />
                  <span>{formData.profile?.location || t('user_profile.no_location')}</span>
                </div>
                <div className="flex items-center gap-3 text-sm text-slate-500 dark:text-slate-400">
                  <Calendar size={18} />
                  <span>
                    {t('user_profile.member_since', {
                      date: formatDateOnly(user.created_at),
                    })}
                  </span>
                </div>
              </div>
              <div className="mt-2 w-full">
                <div className="mb-2 flex items-center justify-between text-xs">
                  <span className="text-slate-500 dark:text-slate-400">
                    {t('user_profile.profile_completion')}
                  </span>
                  <span className="font-medium text-primary dark:text-blue-400">85%</span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-gray-100 dark:bg-gray-700">
                  <div className="h-full w-[85%] rounded-full bg-primary"></div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Right Column: Settings Form */}
        <div className="min-w-0 lg:col-span-2">
          <div className="rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-700 dark:bg-surface-dark">
            {/* Tabs */}
            <div className="overflow-x-auto border-b border-slate-200 px-4 dark:border-slate-700 sm:px-6">
              <nav
                aria-label={t('user_profile.tabs.label', 'Tabs')}
                className="-mb-px flex min-w-max space-x-8"
              >
                {profileSections.map((section) => {
                  const isActive = activeSection === section.id;
                  return (
                    <button
                      key={section.id}
                      type="button"
                      aria-controls={`profile-section-${section.id}`}
                      aria-current={isActive ? 'page' : undefined}
                      className={
                        isActive
                          ? 'border-b-2 border-primary px-1 py-4 text-sm font-medium text-primary dark:text-white'
                          : 'border-b-2 border-transparent px-1 py-4 text-sm font-medium text-slate-500 hover:border-gray-300 hover:text-slate-700 dark:text-slate-400 dark:hover:border-gray-600 dark:hover:text-white'
                      }
                      onClick={() => {
                        handleSectionClick(section.id);
                      }}
                    >
                      {t(section.labelKey)}
                    </button>
                  );
                })}
              </nav>
            </div>
            <div className="p-6">
              <form
                onSubmit={(event) => {
                  void handleSubmit(event);
                }}
              >
                {/* Basic Information Section */}
                <div className="mb-8 scroll-mt-28" id="profile-section-basic">
                  <h3 className="mb-4 text-base font-semibold text-slate-900 dark:text-white">
                    {t('user_profile.basic.title')}
                  </h3>
                  <div className="grid grid-cols-1 gap-x-6 gap-y-6 sm:grid-cols-6">
                    <div className="sm:col-span-3">
                      <label
                        className="block text-sm font-medium leading-6 text-slate-900 dark:text-white"
                        htmlFor="email"
                      >
                        {t('user_profile.basic.email')}
                      </label>
                      <div className="mt-2">
                        <input
                          className="block w-full rounded-md border-0 py-1.5 text-slate-500 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 bg-gray-50 focus:ring-2 focus:ring-inset focus:ring-primary dark:bg-gray-800 dark:ring-gray-700 dark:text-gray-400 sm:text-sm sm:leading-6 cursor-not-allowed"
                          disabled
                          id="email"
                          name="email"
                          type="text"
                          value={formData.email}
                        />
                      </div>
                    </div>
                    <div className="sm:col-span-3">
                      <label
                        className="block text-sm font-medium leading-6 text-slate-900 dark:text-white"
                        htmlFor="name"
                      >
                        {t('user_profile.basic.full_name')}
                      </label>
                      <div className="mt-2">
                        <input
                          className="block w-full rounded-md border-0 py-1.5 text-slate-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-primary dark:bg-background-dark dark:ring-gray-700 dark:text-white sm:text-sm sm:leading-6"
                          id="name"
                          name="name"
                          type="text"
                          value={formData.name}
                          onChange={handleChange}
                        />
                      </div>
                    </div>
                    <div className="sm:col-span-3">
                      <label
                        className="block text-sm font-medium leading-6 text-slate-900 dark:text-white"
                        htmlFor="job_title"
                      >
                        {t('user_profile.basic.job_title')}
                      </label>
                      <div className="mt-2">
                        <input
                          className="block w-full rounded-md border-0 py-1.5 text-slate-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-primary dark:bg-background-dark dark:ring-gray-700 dark:text-white sm:text-sm sm:leading-6"
                          id="job_title"
                          name="job_title"
                          type="text"
                          value={formData.profile?.job_title}
                          onChange={handleChange}
                        />
                      </div>
                    </div>
                    <div className="sm:col-span-3">
                      <label
                        className="block text-sm font-medium leading-6 text-slate-900 dark:text-white"
                        htmlFor="department"
                      >
                        {t('user_profile.basic.department')}
                      </label>
                      <div className="mt-2">
                        <select
                          className="block w-full rounded-md border-0 py-1.5 text-slate-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-primary dark:bg-background-dark dark:ring-gray-700 dark:text-white sm:text-sm sm:leading-6"
                          id="department"
                          name="department"
                          value={formData.profile?.department}
                          onChange={handleChange}
                        >
                          <option value="Engineering">
                            {t('user_profile.basic.departments.engineering', 'Engineering')}
                          </option>
                          <option value="Product">
                            {t('user_profile.basic.departments.product', 'Product')}
                          </option>
                          <option value="Design">
                            {t('user_profile.basic.departments.design', 'Design')}
                          </option>
                          <option value="Marketing">
                            {t('user_profile.basic.departments.marketing', 'Marketing')}
                          </option>
                        </select>
                      </div>
                    </div>
                    <div className="col-span-full">
                      <label
                        className="block text-sm font-medium leading-6 text-slate-900 dark:text-white"
                        htmlFor="avatar_url"
                      >
                        {t('user_profile.basic.avatar_url')}
                      </label>
                      <div className="mt-2">
                        <input
                          ref={avatarUrlInputRef}
                          className="block w-full rounded-md border-0 py-1.5 text-slate-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-primary dark:bg-background-dark dark:ring-gray-700 dark:text-white sm:text-sm sm:leading-6"
                          id="avatar_url"
                          name="avatar_url"
                          placeholder={t('user_profile.basic.avatar_url_placeholder')}
                          type="url"
                          value={formData.profile?.avatar_url ?? ''}
                          onChange={handleChange}
                        />
                      </div>
                    </div>
                    <div className="col-span-full">
                      <label
                        className="block text-sm font-medium leading-6 text-slate-900 dark:text-white"
                        htmlFor="bio"
                      >
                        {t('user_profile.basic.about')}
                      </label>
                      <div className="mt-2">
                        <textarea
                          className="block w-full rounded-md border-0 py-1.5 text-slate-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-primary dark:bg-background-dark dark:ring-gray-700 dark:text-white sm:text-sm sm:leading-6"
                          id="bio"
                          name="bio"
                          rows={3}
                          value={formData.profile?.bio}
                          onChange={handleChange}
                        />
                      </div>
                      <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                        {t('user_profile.basic.about_hint')}
                      </p>
                    </div>
                  </div>
                </div>
                <hr className="border-slate-200 dark:border-slate-700 my-8" />
                {/* Contact Information Section */}
                <div className="mb-8 scroll-mt-28" id="profile-section-contact">
                  <h3 className="mb-4 text-base font-semibold text-slate-900 dark:text-white">
                    {t('user_profile.contact.title')}
                  </h3>
                  <div className="grid grid-cols-1 gap-x-6 gap-y-6 sm:grid-cols-6">
                    <div className="sm:col-span-3">
                      <label
                        className="block text-sm font-medium leading-6 text-slate-900 dark:text-white"
                        htmlFor="phone"
                      >
                        {t('user_profile.contact.phone')}
                      </label>
                      <div className="mt-2">
                        <input
                          className="block w-full rounded-md border-0 py-1.5 text-slate-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-primary dark:bg-background-dark dark:ring-gray-700 dark:text-white sm:text-sm sm:leading-6"
                          id="phone"
                          name="phone"
                          type="tel"
                          value={formData.profile?.phone}
                          onChange={handleChange}
                        />
                      </div>
                    </div>
                    <div className="sm:col-span-3">
                      <label
                        className="block text-sm font-medium leading-6 text-slate-900 dark:text-white"
                        htmlFor="location"
                      >
                        {t('user_profile.contact.location')}
                      </label>
                      <div className="mt-2">
                        <div className="relative rounded-md shadow-sm">
                          <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
                            <MapPin size={18} className="text-gray-400" />
                          </div>
                          <input
                            className="block w-full rounded-md border-0 py-1.5 pl-10 text-slate-900 ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-primary dark:bg-background-dark dark:ring-gray-700 dark:text-white sm:text-sm sm:leading-6"
                            id="location"
                            name="location"
                            placeholder={t('user_profile.contact.location_placeholder')}
                            type="text"
                            value={formData.profile?.location}
                            onChange={handleChange}
                          />
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
                <hr className="border-slate-200 dark:border-slate-700 my-8" />
                {/* Preferences Section */}
                <div className="mb-8 scroll-mt-28" id="profile-section-preferences">
                  <h3 className="mb-4 text-base font-semibold text-slate-900 dark:text-white">
                    {t('user_profile.preferences.title')}
                  </h3>
                  <div className="grid grid-cols-1 gap-x-6 gap-y-6 sm:grid-cols-6">
                    <div className="sm:col-span-3">
                      <label
                        className="block text-sm font-medium leading-6 text-slate-900 dark:text-white"
                        htmlFor="language"
                      >
                        {t('user_profile.preferences.language')}
                      </label>
                      <div className="mt-2">
                        <select
                          className="block w-full rounded-md border-0 py-1.5 text-slate-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-primary dark:bg-background-dark dark:ring-gray-700 dark:text-white sm:text-sm sm:leading-6"
                          id="language"
                          name="preferred_language"
                          value={formData.preferred_language ?? 'en-US'}
                          onChange={handleChange}
                        >
                          <option value="en-US">
                            {t('user_profile.preferences.languages.enUS', 'English (US)')}
                          </option>
                          <option value="zh-CN">
                            {t(
                              'user_profile.preferences.languages.zhSimplified',
                              'Chinese (Simplified)'
                            )}
                          </option>
                        </select>
                      </div>
                    </div>
                    <div className="sm:col-span-3">
                      <label
                        className="block text-sm font-medium leading-6 text-slate-900 dark:text-white"
                        htmlFor="timezone"
                      >
                        {t('user_profile.preferences.timezone')}
                      </label>
                      <div className="mt-2">
                        <select
                          className="block w-full rounded-md border-0 py-1.5 text-slate-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-primary dark:bg-background-dark dark:ring-gray-700 dark:text-white sm:text-sm sm:leading-6"
                          id="timezone"
                          name="timezone"
                          value={formData.profile?.timezone}
                          onChange={handleChange}
                        >
                          <option value="Pacific Time (US & Canada)">
                            {t(
                              'user_profile.preferences.timezones.pacific',
                              'Pacific Time (US & Canada)'
                            )}
                          </option>
                          <option value="Eastern Time (US & Canada)">
                            {t(
                              'user_profile.preferences.timezones.eastern',
                              'Eastern Time (US & Canada)'
                            )}
                          </option>
                          <option value="London (UTC)">
                            {t('user_profile.preferences.timezones.london', 'London (UTC)')}
                          </option>
                        </select>
                      </div>
                    </div>
                  </div>
                </div>
                <hr className="border-slate-200 dark:border-slate-700 my-8" />
                {/* Security Section */}
                <div className="mb-8 scroll-mt-28" id="profile-section-security">
                  <h3 className="mb-4 text-base font-semibold text-slate-900 dark:text-white">
                    {t('user_profile.security.title')}
                  </h3>
                  <div className="flex flex-col gap-4 rounded-lg border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-background-dark sm:flex-row sm:items-center sm:justify-between">
                    <div className="flex items-start gap-3">
                      <div className="mt-0.5 flex h-9 w-9 flex-none items-center justify-center rounded-md bg-primary/10 text-primary dark:bg-blue-500/15 dark:text-blue-300">
                        <KeyRound size={18} />
                      </div>
                      <div>
                        <p className="text-sm font-semibold text-slate-900 dark:text-white">
                          {t('user_profile.security.password_title')}
                        </p>
                        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                          {t('user_profile.security.password_desc')}
                        </p>
                      </div>
                    </div>
                    <Link
                      to="/force-change-password"
                      className="inline-flex items-center justify-center rounded-md bg-primary px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-primary-dark focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                    >
                      {t('user_profile.security.change_password')}
                    </Link>
                  </div>
                </div>

                {/* Action Buttons */}
                <div className="flex items-center justify-end gap-x-4 border-t border-slate-200 pt-6 dark:border-slate-700">
                  <button
                    className="rounded-md px-3 py-2 text-sm font-semibold text-slate-900 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 dark:ring-gray-600 dark:text-white dark:hover:bg-gray-800"
                    type="button"
                    disabled={isLoading}
                    onClick={handleCancel}
                  >
                    {t('user_profile.buttons.cancel')}
                  </button>
                  <button
                    className="rounded-md bg-primary px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-primary-dark focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:opacity-50"
                    type="submit"
                    disabled={isLoading}
                  >
                    {isLoading ? t('user_profile.buttons.saving') : t('user_profile.buttons.save')}
                  </button>
                </div>
              </form>
            </div>
          </div>
        </div>
      </div>

      {/* Toast Notification */}
      {showSuccess && (
        <div className="pointer-events-none fixed inset-0 flex items-end px-4 py-6 sm:items-start sm:p-6 z-50">
          <div className="flex w-full flex-col items-center space-y-4 sm:items-end">
            <div className="pointer-events-auto w-full max-w-sm overflow-hidden rounded-lg bg-white shadow-lg ring-1 ring-black ring-opacity-5 dark:bg-surface-dark dark:ring-white dark:ring-opacity-10 transform transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-300 ease-out translate-y-0 opacity-100">
              <div className="p-4">
                <div className="flex items-start">
                  <div className="flex-shrink-0">
                    <CheckCircle size={16} className="text-green-400" />
                  </div>
                  <div className="ml-3 w-0 flex-1 pt-0.5">
                    <p className="text-sm font-medium text-slate-900 dark:text-white">
                      {t('user_profile.toast.success_title')}
                    </p>
                    <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                      {t('user_profile.toast.success_desc')}
                    </p>
                  </div>
                  <div className="ml-4 flex flex-shrink-0">
                    <button
                      type="button"
                      className="inline-flex rounded-md bg-white text-gray-400 hover:text-gray-500 focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 dark:bg-surface-dark dark:hover:text-gray-300"
                      onClick={() => {
                        setShowSuccess(false);
                      }}
                    >
                      <span className="sr-only">{t('common.close', 'Close')}</span>
                      <X size={14} />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
