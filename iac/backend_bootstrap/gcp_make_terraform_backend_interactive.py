import subprocess
import shutil
import json
import sys
import re
from abc import ABC, abstractmethod
from datetime import datetime

DEFAULT_LOCATION = 'europe-west4'

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
        return e
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
        if isinstance(self.original_project, subprocess.CompletedProcess):
            self.original_project = self.original_project.stdout.strip()
        else:
            self.original_project = None

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
            context.transition_to(None)
            return

        auth_process = run_command("gcloud auth list --filter=status:ACTIVE --format=json", capture_output=True, text=True, suppress_errors=True)
        if not isinstance(auth_process, subprocess.CompletedProcess) or not auth_process.stdout.strip() or auth_process.stdout.strip() == '[]':
            print(f"{Color.YELLOW}You are not logged into gcloud.{Color.ENDC}")
            if input("Would you like to log in now? (y/n): ").lower() == 'y':
                run_command("gcloud auth login")
                auth_process = run_command("gcloud auth list --filter=status:ACTIVE --format=json", capture_output=True, text=True, suppress_errors=True)
                if not isinstance(auth_process, subprocess.CompletedProcess) or not auth_process.stdout.strip() or auth_process.stdout.strip() == '[]':
                    print(f"{Color.RED}Login failed or was cancelled. Exiting.{Color.ENDC}")
                    context.transition_to(None)
                    return
            else:
                context.transition_to(None)
                return
        
        print(f"{Color.GREEN}✔ gcloud is installed and you are authenticated.{Color.ENDC}")
        context.transition_to(SelectProjectState())


class SelectProjectState(State):
    def handle(self, context: SetupContext):
        print("\n--- Selecting Google Cloud Project ---")
        projects_process = run_command("gcloud projects list --format=json", capture_output=True, text=True)
        if not isinstance(projects_process, subprocess.CompletedProcess):
            context.transition_to(None)
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

        if isinstance(run_command(create_command), subprocess.CompletedProcess):
            context.project_id = project_id
            context.transition_to(LinkBillingState())
        else:
            print(f"{Color.YELLOW}Project creation failed. Please try again.{Color.ENDC}")
            context.transition_to(SelectProjectState())


class LinkBillingState(State):
    def handle(self, context: SetupContext):
        print(f"\n--- Linking Billing Account to '{context.project_id}' ---")
        billing_process = run_command("gcloud beta billing accounts list --format=json", capture_output=True, text=True)
        if not isinstance(billing_process, subprocess.CompletedProcess) or not billing_process.stdout:
            context.transition_to(SelectProjectState())
            return

        billing_accounts = json.loads(billing_process.stdout)
        if not billing_accounts:
            print(f"{Color.RED}No billing accounts found.{Color.ENDC}")
            context.transition_to(SelectProjectState())
            return

        billing_id = billing_accounts[0]['name'].split('/')[-1]
        
        if isinstance(run_command(f"gcloud beta billing projects link {context.project_id} --billing-account={billing_id}"), subprocess.CompletedProcess):
            context.transition_to(CheckBillingState())
        else:
            print(f"{Color.RED}Failed to link billing account.{Color.ENDC}")
            context.transition_to(SelectProjectState())


class CheckBillingState(State):
    def handle(self, context: SetupContext):
        print(f"\n--- Verifying Billing for '{context.project_id}' ---")
        billing_info = run_command(f"gcloud beta billing projects describe {context.project_id} --format=json", capture_output=True, text=True, suppress_errors=True)
        
        if isinstance(billing_info, subprocess.CompletedProcess) and billing_info.stdout and json.loads(billing_info.stdout).get('billingEnabled'):
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
        print(f"\n--- Checking for Existing Buckets in '{context.project_id}' ---")
        list_command = f"gcloud storage buckets list --project={context.project_id}"
        list_process = run_command(list_command, capture_output=True, text=True, suppress_errors=True)
        
        if isinstance(list_process, subprocess.CompletedProcess) and list_process.stdout:
            print("Found existing buckets:")
            print(f"{Color.CYAN}{list_process.stdout.strip()}{Color.ENDC}")
        else:
            print("No buckets found in this project.")
            
        print("\n--- Configuring GCS Bucket ---")
        suggested_name = f"{context.project_id}-tfstate"
        context.bucket_name = input(f"Enter a bucket name (press Enter for '{suggested_name}'): ") or suggested_name
        context.location = input(f"Enter a location (e.g., {DEFAULT_LOCATION}) (press Enter for '{DEFAULT_LOCATION}'): ") or DEFAULT_LOCATION
        context.transition_to(CreateBucketState())


class CreateBucketState(State):
    def handle(self, context: SetupContext):
        print(f"\n--- Ensuring Bucket '{context.bucket_name}' Exists and is Configured ---")
        
        while True: # Loop until the bucket is successfully created or user aborts
            create_command = (
                f"gcloud storage buckets create gs://{context.bucket_name} "
                f"--project={context.project_id} "
                f"--location={context.location} "
                f"--uniform-bucket-level-access"
            )
            result = run_command(create_command, capture_output=True, text=True, suppress_errors=True)
            
            if isinstance(result, subprocess.CompletedProcess):
                print(f"{Color.GREEN}✔ Bucket '{context.bucket_name}' created successfully.{Color.ENDC}")
                break # Exit loop and proceed to versioning

            elif isinstance(result, subprocess.CalledProcessError):
                stderr_str = result.stderr 
                if "already exists" in stderr_str or "you already own it" in stderr_str:
                    print(f"{Color.YELLOW}Bucket '{context.bucket_name}' already exists.{Color.ENDC}")
                    choice = input(
                        f"Choose an action: [{Color.BOLD}D{Color.ENDC}]estroy & Re-create, [{Color.BOLD}R{Color.ENDC}]ename old & Re-create, [{Color.BOLD}A{Color.ENDC}]bort: "
                    ).lower()

                    if choice == 'd':
                        confirm = input(f"{Color.RED}{Color.BOLD}This will PERMANENTLY DELETE the bucket and all its contents. Are you sure? (y/n): {Color.ENDC}").lower()
                        if confirm == 'y':
                            print(f"Destroying gs://{context.bucket_name}...")
                            destroy_command = f"gcloud storage buckets delete gs://{context.bucket_name} --quiet"
                            
                            if not isinstance(run_command(destroy_command), subprocess.CompletedProcess):
                                print(f"{Color.RED}Failed to destroy bucket. Aborting.{Color.ENDC}")
                                context.transition_to(None)
                                return
                            print("Destruction complete. Retrying creation...")
                            continue 
                        else:
                            print("Destruction cancelled.")
                            context.transition_to(None) 
                            return

                    elif choice == 'r':
                        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                        new_name = f"{context.bucket_name}-old-{timestamp}"
                        print(f"Renaming gs://{context.bucket_name} to gs://{new_name}...")
                        rename_command = f"gsutil mv gs://{context.bucket_name} gs://{new_name}"
                        
                        if not isinstance(run_command(rename_command), subprocess.CompletedProcess):
                            print(f"{Color.RED}Failed to rename bucket. Aborting.{Color.ENDC}")
                            context.transition_to(None)
                            return
                        print("Rename complete. Retrying creation...")
                        continue 
                    
                    else: # Abort
                        print("Operation aborted by user.")
                        context.transition_to(None)
                        return
                else:
                    print(f"{Color.RED}{stderr_str.strip()}{Color.ENDC}")
                    context.transition_to(None)
                    return
            else: 
                print(f"{Color.RED}An unexpected error occurred. Aborting.{Color.ENDC}")
                context.transition_to(None)
                return

        # --- This section only runs after a successful bucket creation ---
        print("Ensuring versioning is enabled...")
        versioning_command = f"gcloud storage buckets update gs://{context.bucket_name} --versioning --project={context.project_id}"
        if not isinstance(run_command(versioning_command), subprocess.CompletedProcess):
            print(f"{Color.RED}Failed to enable versioning.{Color.ENDC}")
            context.transition_to(None)
            return
        print(f"{Color.GREEN}✔ Versioning is enabled.{Color.ENDC}")
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
        context.transition_to(None)


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
