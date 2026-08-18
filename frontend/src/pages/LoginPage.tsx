import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Input, Card, CardHeader, CardContent, FormField, useToast } from "@/components/ui";
import { useAuthStore } from "@/stores/authStore";
import { login } from "@/api";

export function LoginPage() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const { isAuthenticated, login: storeLogin } = useAuthStore();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (isAuthenticated) {
      navigate("/");
    }
  }, [isAuthenticated, navigate]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);

    try {
      const response = await login(username, password);
      storeLogin(response.access_token, response.refresh_token, response.csrf_token);
      navigate("/");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Login failed";
      setError(message);
      toast({ title: message, tone: "danger" });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <div className="text-center">
            <h1 className="text-2xl font-bold text-electric-blue">Taskflows</h1>
            <p className="text-muted mt-1">Sign in to your account</p>
          </div>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <FormField label="Username" required>
              <Input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                autoComplete="username"
                autoFocus
              />
            </FormField>

            <FormField error={error} label="Password" required>
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
              />
            </FormField>

            <Button
              type="submit"
              variant="primary"
              fullWidth
              loading={isLoading}
            >
              Sign In
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
