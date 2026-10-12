import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: unknown) {
    console.error("ErrorBoundary caught an error:", error, errorInfo);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center h-screen bg-gray-950 text-white p-6 text-center font-sans">
          <div className="w-16 h-16 rounded-2xl bg-red-900/30 border border-red-800 flex items-center justify-center text-3xl mb-4">
            ⚠️
          </div>
          <h1 className="text-xl font-bold mb-2">Something went wrong</h1>
          <p className="text-sm text-gray-400 max-w-md mb-6 leading-relaxed">
            {this.state.error?.message || "An unexpected error occurred in the application."}
          </p>
          <button
            onClick={this.handleReset}
            className="px-5 py-2.5 bg-blue-600 hover:bg-blue-500 rounded-xl text-sm font-medium transition-colors"
          >
            Reload Application
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
