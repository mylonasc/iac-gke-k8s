#!/usr/bin/env python3

#!/usr/bin/env python3
import subprocess
import sys
import os

def run_gcloud_command(command):
    """Runs a gcloud command and returns its output."""
    try:
        # We use shell=True for simplicity with gcloud's complex command structures
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except FileNotFoundError:
        print("\n[ERROR] `gcloud` command not found.")
        print("Please ensure the Google Cloud SDK is installed and in your system's PATH.")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        error_message = e.stderr.strip()
        print(f"\n[ERROR] A gcloud command failed:\n--- GCLOUD ERROR ---\n{error_message}\n--------------------")
        # Provide a more specific hint for the most common authentication error.
        if "You do not currently have an active account selected" in error_message:
            print("\n[HINT] It looks like you're not logged into gcloud.")
            print("Please run `gcloud auth login` in your terminal and try again.")
        sys.exit(1)

def present_selection(prompt, options):
    """
    Presents a list of options to the user and returns the selected option.
    Handles user input validation.
    """
    if not options:
        return None

    print(f"\n{prompt}")
    for i, option in enumerate(options, 1):
        print(f"  [{i}] {option}")

    while True:
        try:
            choice = input("Enter your choice (number): ")
            if not choice: continue # Handle empty input
            
            index = int(choice) - 1
            if 0 <= index < len(options):
                return options[index]
            else:
                print(f"[Warning] Invalid number. Please enter a number between 1 and {len(options)}.")
        except ValueError:
            print("[Warning] Invalid input. Please enter a number.")
        except (KeyboardInterrupt, EOFError):
            print("\n\nExiting.")
            sys.exit(0)

def main():
    """Main function to guide the user through the selection process."""
    print("--- GKE Kubectl Configuration Helper ---")
    
    # 1. Select Project
    print("\nFetching available Google Cloud projects...")
    projects_str = run_gcloud_command('gcloud projects list --format="value(projectId)"')
    projects = projects_str.split('\n') if projects_str else []
    
    if not projects:
        print("[ERROR] No projects found. Please ensure you are logged in (`gcloud auth login`).")
        sys.exit(1)
        
    selected_project = present_selection("Please select your Project ID:", projects)
    if not selected_project: # Should not happen if projects are found, but good practice
        print("[ERROR] No project was selected.")
        sys.exit(1)

    print(f"\n> Project selected: {selected_project}")

    # 2. Select Cluster
    print(f"\nFetching clusters in project '{selected_project}'...")
    # Get cluster name and location in one go, separated by a tab for easy splitting
    clusters_str = run_gcloud_command(
        f'gcloud container clusters list --project="{selected_project}" --format="value(name,location)"'
    )
    
    if not clusters_str:
        print(f"[ERROR] No GKE clusters found in project '{selected_project}'.")
        sys.exit(1)

    clusters_list = clusters_str.split('\n')
    
    # We store the raw data and present a formatted version to the user
    cluster_options_display = [f"{line.split()[0]} ({line.split()[1]})" for line in clusters_list]
    selected_cluster_display = present_selection("Please select your GKE cluster:", cluster_options_display)

    # Find the original data corresponding to the user's display selection
    selected_cluster_index = cluster_options_display.index(selected_cluster_display)
    selected_cluster_data = clusters_list[selected_cluster_index].split()

    cluster_name = selected_cluster_data[0]
    compute_zone = selected_cluster_data[1]

    print(f"> Cluster selected: {cluster_name} in {compute_zone}")

    # 3. Generate and display the final command
    print("\n----------------------------------------")
    print("Configuration Complete!")
    print("Your parameters are:")
    print(f"  PROJECT_ID:   {selected_project}")
    print(f"  CLUSTER_NAME: {cluster_name}")
    print(f"  COMPUTE_ZONE: {compute_zone}")
    print("----------------------------------------")
    
    final_command = (
        f"gcloud container clusters get-credentials {cluster_name} "
        f"--zone {compute_zone} --project {selected_project}"
    )

    print("\nTo configure kubectl, copy and run the following command in your terminal:\n")
    print(f"    {final_command}\n")

    # 4. (Optional) Ask the user if they want to run the command
    try:
        run_now = input("Would you like to run this command now? (y/N): ").lower().strip()
        if run_now == 'y':
            print("\nExecuting command...")
            os.system(final_command)
            print("\n✅ kubectl has been configured successfully!")
        else:
            print("\nConfiguration skipped. Please run the command manually.")
    except (KeyboardInterrupt, EOFError):
        print("\n\nConfiguration skipped. Exiting.")

if __name__ == "__main__":
    main()




