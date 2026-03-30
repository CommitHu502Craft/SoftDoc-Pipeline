export interface Project {
  id: string;
  name: string;
  progress: number;
  status: 'idle' | 'running' | 'completed' | 'error';
  createdAt: string;
  currentStep?: string;
  files: {
    plan: boolean;
    html: boolean;
    screenshots: boolean;
    code: boolean;
    document: boolean;
    pdf: boolean;
  };
}

export interface LogEntry {
  id: string;
  timestamp: string;
  level: 'INFO' | 'SUCCESS' | 'WARNING' | 'ERROR';
  message: string;
}

export interface SubmitItem {
  id: string;
  projectName: string;
  status: 'pending' | 'submitting' | 'completed' | 'failed';
  addedAt: string;
  error?: string;
}

export interface Account {
  id: string;
  username: string;
  description: string;
}

export interface StepStatus {
  id: string;
  title: string;
  status: 'completed' | 'running' | 'pending';
}