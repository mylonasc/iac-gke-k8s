import subprocess
import shutil
import json
import sys
import re
from abc import ABC, abstractmethod

# --- ANSI Color Codes for better readability ---
class Color:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

# --- Helper Functions ---
def run_command(command, capture_output=False, text=False, suppress_errors=False):
    """A helper function to run shell commands and handle errors."""
    try:
        # The `stderr` argument is removed from the call to prevent conflict with `capture_output`.
        # `capture_output=True` handles capturing stderr automatically.
        # The `suppress_errors` flag is now correctly used only in the exception block below.
        process = subprocess.run(
            command, check=True, capture_output=capture_output, text=text, shell=True
        )
        return process
    except subprocess.CalledProcessError as e:
        if not suppress_errors:
            print(f"{Color.RED}Error executing command: {command}{Color.ENDC}")
            if e.stderr:
                stderr_output = e.stderr.decode('utf-8').strip() if isinstance(e.stderr, bytes) else e.stderr.strip()
                print(f"{Color.RED}{stderr_output}{Color.ENDC}")
        return None
    except FileNotFoundError:
        print(f"{Color.RED}Error: Command '{command.split()[0]}' not found. Is gcloud installed and in your PATH?{Color.ENDC}")
        return None

# --- State Machine Implementation ---

class SetupContext:
    """The Context class that manages the state and shared data."""
    def __init__(self):
        self._state = CheckPrerequisitesState()
        self.project_id = None
        self.bucket_name = None
        self.location = None
        self.original_project = run_command("gcloud config get-value project", capture_output=True, text=True, suppress_errors=True)
        if self.original_project:
            self.original_project = self.original_project.stdout.strip()

    def transition_to(self, state):
        if state:
            print(f"{Color.BLUE}--> Transitioning to {state.__class__.__name__}{Color.ENDC}")
        self._state = state

    def run(self):
        while self._state is not None:
            self._state.handle(self)
    
    def cleanup(self):
        if self.original_project:
            run_command(f"gcloud config set project {self.original_project}", suppress_errors=True)
            print(f"\nRestored original gcloud project configuration to '{self.original_project}'.")


class State(ABC):
    """Abstract base class for all State classes."""
    @abstractmethod
    def handle(self, context: SetupContext):
        pass


class CheckPrerequisitesState(State):
    def handle(self, context: SetupContext):
        print("\n--- Checking Prerequisites ---")
        if not shutil.which("gcloud"):
            print(f"{Color.RED}Error: 'gcloud' CLI is not installed or not in your system's PATH.{Color.ENDC}")
            context.transition_to(None) # End
            return

        auth_process = run_command("gcloud auth list --filter=status:ACTIVE --format=json", capture_output=True, text=True, suppress_errors=True)
        if not auth_process or not auth_process.stdout.strip() or auth_process.stdout.strip() == '[]':
            print(f"{Color.YELLOW}You are not logged into gcloud.{Color.ENDC}")
            if input("Would you like to log in now? (y/n): ").lower() == 'y':
                # Re-check after login attempt
                run_command("gcloud auth login")
                auth_process = run_command("gcloud auth list --filter=status:ACTIVE --format=json", capture_output=True, text=True, suppress_errors=True)
                if not auth_process or not auth_process.stdout.strip() or auth_process.stdout.strip() == '[]':
                    print(f"{Color.RED}Login failed or was cancelled. Exiting.{Color.ENDC}")
                    context.transition_to(None)
                    return
            else:
                context.transition_to(None) # End
                return
        
        print(f"{Color.GREEN}✔ gcloud is installed and you are authenticated.{Color.ENDC}")
        context.transition_to(SelectProjectState())


class SelectProjectState(State):
    def handle(self, context: SetupContext):
        print("\n--- Selecting Google Cloud Project ---")
        projects_process = run_command("gcloud projects list --format=json", capture_output=True, text=True)
        if not projects_process:
            context.transition_to(None) # End
            return

        projects = json.loads(projects_process.stdout)
        print("Available projects:")
        for i, project in enumerate(projects):
            print(f"  {i + 1}: {project['name']} ({Color.CYAN}{project['projectId']}{Color.ENDC})")
        print(f"  {Color.YELLOW}C: Create a new project{Color.ENDC}")

        while True:
            choice_str = input("Select a project by number or enter 'C': ").lower()
            if choice_str == 'c':
                context.transition_to(CreateProjectState())
                return
            try:
                choice = int(choice_str) - 1
                if 0 <= choice < len(projects):
                    context.project_id = projects[choice]['projectId']
                    context.transition_to(CheckBillingState())
                    return
                else:
                    print(f"{Color.YELLOW}Invalid number.{Color.ENDC}")
            except ValueError:
                print(f"{Color.YELLOW}Please enter a valid number or 'C'.{Color.ENDC}")


class CreateProjectState(State):
    def handle(self, context: SetupContext):
        print("\n--- Creating a New Google Cloud Project ---")
        project_id = input("Enter a unique project ID (e.g., 'gcp-ops-data'): ").lower()
        if not re.match("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", project_id):
            print(f"{Color.RED}Invalid project ID format.{Color.ENDC}")
            context.transition_to(SelectProjectState())
            return
        
        project_name = input(f"Enter a display name for '{project_id}': ")
        create_command = f'gcloud projects create {project_id} --name="{project_name}"'

        if run_command(create_command):
            context.project_id = project_id
            context.transition_to(LinkBillingState())
        else:
            print(f"{Color.YELLOW}Project creation failed. Please try again.{Color.ENDC}")
            context.transition_to(SelectProjectState())


class LinkBillingState(State):
    def handle(self, context: SetupContext):
        print(f"\n--- Linking Billing Account to '{context.project_id}' ---")
        billing_process = run_command("gcloud beta billing accounts list --format=json", capture_output=True, text=True)
        if not billing_process or not billing_process.stdout:
            context.transition_to(SelectProjectState())
            return

        billing_accounts = json.loads(billing_process.stdout)
        if not billing_accounts:
            print(f"{Color.RED}No billing accounts found.{Color.ENDC}")
            context.transition_to(SelectProjectState())
            return

        billing_id = billing_accounts[0]['name'].split('/')[-1]
        # (User selection logic omitted for brevity, defaults to first account)
        
        if run_command(f"gcloud beta billing projects link {context.project_id} --billing-account={billing_id}"):
            context.transition_to(CheckBillingState())
        else:
            print(f"{Color.RED}Failed to link billing account.{Color.ENDC}")
            context.transition_to(SelectProjectState())


class CheckBillingState(State):
    def handle(self, context: SetupContext):
        print(f"\n--- Verifying Billing for '{context.project_id}' ---")
        billing_info = run_command(f"gcloud beta billing projects describe {context.project_id} --format=json", capture_output=True, text=True, suppress_errors=True)
        
        if billing_info and billing_info.stdout and json.loads(billing_info.stdout).get('billingEnabled'):
            print(f"{Color.GREEN}✔ Billing is active.{Color.ENDC}")
            run_command(f"gcloud config set project {context.project_id}")
            context.transition_to(GetBucketDetailsState())
        else:
            print(f"{Color.RED}Billing is not enabled for this project.{Color.ENDC}")
            if input("Would you like to attempt to enable billing now? (y/n): ").lower() == 'y':
                context.transition_to(LinkBillingState())
            else:
                context.transition_to(SelectProjectState())


class GetBucketDetailsState(State):
    def handle(self, context: SetupContext):
        print("\n--- Configuring GCS Bucket ---")
        suggested_name = f"{context.project_id}-tfstate"
        context.bucket_name = input(f"Enter a globally unique bucket name (press Enter for '{suggested_name}'): ") or suggested_name
        context.location = input("Enter a location (e.g., us-central1) (press Enter for 'us-central1'): ") or "us-central1"
        context.transition_to(CreateBucketState())


class CreateBucketState(State):
    def handle(self, context: SetupContext):
        print("\n--- Creating GCS Bucket ---")
        if not run_command(f"gcloud storage buckets create gs://{context.bucket_name} --location={context.location} --project={context.project_id}"):
            context.transition_to(None) # End Failure
            return
            
        if not run_command(f"gcloud storage buckets update gs://{context.bucket_name} --versioning"):
            context.transition_to(None) # End Failure
            return

        print(f"{Color.GREEN}✔ Bucket '{context.bucket_name}' created and versioning enabled.{Color.ENDC}")
        context.transition_to(SuccessState())


class SuccessState(State):
    def handle(self, context: SetupContext):
        backend_config = f"""# Save this content in a file named backend.tf
terraform {{
  backend "gcs" {{
    bucket  = "{context.bucket_name}"
    prefix  = "terraform/state"
  }}
}}
"""
        print(f"\n{Color.HEADER}{Color.BOLD}--- Terraform Configuration ---{Color.ENDC}")
        print("Your GCS backend is ready! Add the following block to your Terraform project:")
        print(f"{Color.CYAN}{backend_config}{Color.ENDC}")
        
        if input("Save this configuration to 'backend.tf'? (y/n): ").lower() == 'y':
            with open("backend.tf", "w") as f: f.write(backend_config)
            print(f"{Color.GREEN}✔ Saved to backend.tf{Color.ENDC}")
        
        print(f"\n{Color.BOLD}Setup complete! Run {Color.YELLOW}'terraform init'{Color.ENDC} in your project.")
        context.transition_to(None) # End


def main():
    """Main script execution function."""
    print(f"{Color.HEADER}{Color.BOLD}GCP Terraform Backend Setup Assistant (State Machine Version){Color.ENDC}")
    context = SetupContext()
    try:
        context.run()
    finally:
        context.cleanup()


if __name__ == "__main__":
    main()


