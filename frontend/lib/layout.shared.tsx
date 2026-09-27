import type { BaseLayoutProps } from 'fumadocs-ui/layouts/shared';
import { BrandMark } from '@/components/layout/BrandMark';
import { appName, gitConfig } from './shared';

export function baseOptions(): BaseLayoutProps {
  return {
    nav: {
      title: (
        <span className="inline-flex items-center gap-2.5">
          <BrandMark className="h-5 w-5" title="" />
          {appName}
        </span>
      ),
    },
    githubUrl: `https://github.com/${gitConfig.user}/${gitConfig.repo}`,
  };
}
