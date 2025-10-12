#!/usr/bin/env python3
import subprocess
import json
import os
import sys
from pathlib import Path

# Define the path for the cache file in the user's home directory
CACHE_FILE = Path.home() / ".gke_cluster_cache.json"

def run_command(command, capture_output=True, text=True, shell=False):
    """Executes a shell command and returns the result."""
    try:
        # Using a list of arguments is safer than shell=True
        if shell:
            # Use shell=True only when the command is a string and needs shell features
            result = subprocess.run(
                command,
                capture_output=capture_output,
                text=text,
                check=True,
                shell=True
            )
        else:
             result = subprocess.run(
                command,
                capture_output=capture_output,
                text=text,
                check=True
            )
        return result
    except FileNotFoundError:
        print(f"Error: Command '{command[0]}' not found. Is gcloud or kubectl installed and in your PATH?")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {' '.join(command)}")
        print(f"Stderr: {e.stderr}")
        # Don't exit for describe commands as the cluster might be in a weird state
        if "describe" in command or "operations" in command or "logging" in command:
             return e
        sys.exit(1)

def load_cache():
    """Loads the cluster cache from the JSON file."""
    if not CACHE_FILE.exists():
        return {}
    with open(CACHE_FILE, 'r') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            # Handle case where cache file is corrupted or empty
            return {}

def save_cache(cache_data):
    """Saves the given data to the cluster cache JSON file."""
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache_data, f, indent=4)
    print(f"Cache updated successfully at {CACHE_FILE}")

def select_from_list(items, title):
    """Displays a list of items and prompts the user to select one."""
    print(f"\n--- {title} ---")
    if not items:
        print("No items found.")
        return None

    for i, item in enumerate(items):
        print(f"[{i + 1}] {item}")

    while True:
        try:
            choice = input(f"Select a number (1-{len(items)}): ")
            if choice.lower() == 'q':
                return None
            index = int(choice) - 1
            if 0 <= index < len(items):
                return items[index]
            else:
                print("Invalid number, please try again.")
        except ValueError:
            print("Invalid input, please enter a number.")

def get_projects():
    """Fetches a list of all accessible GCP projects."""
    print("Fetching available projects...")
    result = run_command(["gcloud", "projects", "list", "--format=json"])
    projects = json.loads(result.stdout)
    # Return a list of project IDs, sorted for consistency
    return sorted([p['projectId'] for p in projects])

def get_clusters(project_id):
    """Fetches a list of GKE clusters for a given project."""
    print(f"Fetching clusters for project '{project_id}'...")
    result = run_command([
        "gcloud", "container", "clusters", "list",
        f"--project={project_id}",
        "--format=json"
    ])
    clusters = json.loads(result.stdout)
    if not clusters:
        print(f"No GKE clusters found in project '{project_id}'.")
        return []
    # Return a list of cluster names and their locations
    return sorted([(c['name'], c['location']) for c in clusters], key=lambda x: x[0])

def get_cluster_credentials(project_id, cluster_name, location):
    """Gets credentials for a specific cluster and updates kubeconfig."""
    print(f"Getting credentials for cluster '{cluster_name}'...")
    run_command([
        "gcloud", "container", "clusters", "get-credentials",
        cluster_name,
        f"--project={project_id}",
        # Handle both regional and zonal clusters by checking location format
        "--region" if len(location.split('-')) == 2 else "--zone",
        location
    ])
    # The context name format is predictable
    context_name = f"gke_{project_id}_{location}_{cluster_name}"
    print(f"\nSuccessfully configured kubectl context: '{context_name}'")
    return context_name

def check_finalizers():
    """Checks for finalizers on all GKE clusters in a selected project."""
    projects = get_projects()
    selected_project = select_from_list(projects, "Select a Project to Check for Finalizers")
    if not selected_project:
        return

    clusters = get_clusters(selected_project)
    if not clusters:
        return

    print(f"\n--- Checking Finalizers for Clusters in '{selected_project}' ---")
    for cluster_name, location in clusters:
        print(f"Checking cluster: {cluster_name} ({location})...")
        # Determine if it's a region or zone based on the number of hyphens
        location_flag = "--region" if len(location.split('-')) == 2 else "--zone"

        command = [
            "gcloud", "container", "clusters", "describe",
            cluster_name,
            f"--project={selected_project}",
            location_flag,
            location,
            "--format=value(finalizers)"
        ]
        
        try:
            result = run_command(command)
            finalizers = result.stdout.strip()

            if finalizers:
                print(f"  └── Found Finalizers: {finalizers}")
            else:
                print(f"  └── No finalizers found.")
        except SystemExit:
            # Catch exit from run_command and report gracefully
            print(f"  └── Could not retrieve information for cluster '{cluster_name}'. It may be in an unusual state.")

def debug_cluster():
    """Gathers and displays diagnostic information for a specific cluster."""
    projects = get_projects()
    selected_project = select_from_list(projects, "Select a Project to Debug")
    if not selected_project:
        return

    clusters = get_clusters(selected_project)
    if not clusters:
        return
        
    cluster_display_list = [f"{name} ({loc})" for name, loc in clusters]
    selected_cluster_display = select_from_list(cluster_display_list, f"Select a Cluster in '{selected_project}' to Debug")
    if not selected_cluster_display:
        return

    selected_index = cluster_display_list.index(selected_cluster_display)
    cluster_name, location = clusters[selected_index]
    location_flag = "--region" if len(location.split('-')) == 2 else "--zone"

    print(f"\n--- 🕵️  Debugging Cluster: {cluster_name} ({location}) ---")

    # 1. Get Basic Cluster Status
    print("\n[1/3] Fetching Cluster Status & Conditions...")
    describe_cmd = [
        "gcloud", "container", "clusters", "describe", cluster_name,
        f"--project={selected_project}", location_flag, location,
        "--format=yaml(status, conditions)"
    ]
    describe_result = run_command(describe_cmd)
    print(describe_result.stdout or describe_result.stderr)

    # 2. Get Node Pool Status
    print("\n[2/3] Fetching Node Pool Status...")
    nodepool_cmd = [
        "gcloud", "container", "node-pools", "list",
        f"--cluster={cluster_name}",
        f"--project={selected_project}", location_flag, location,
        "--format=table(name, status, version)"
    ]
    nodepool_result = run_command(nodepool_cmd)
    print(nodepool_result.stdout or nodepool_result.stderr)
    
    # 3. Get Recent Cluster Operations
    print("\n[3/3] Fetching Last 5 Cluster Operations...")
    operations_cmd = [
        "gcloud", "container", "operations", "list",
        f"--project={selected_project}",
        # Filter by the cluster's unique resource link
        f"--filter=targetLink.scope().segment(-1)='{cluster_name}'",
        "--limit=5",
        "--sort-by=~startTime",
        "--format=table(name, operationType, status, statusMessage, startTime.iso())"
    ]
    operations_result = run_command(operations_cmd)
    print(operations_result.stdout or operations_result.stderr)
    print("--- Debugging Complete ---")

def force_delete_cluster():
    """Attempts to delete a cluster and provides follow-up steps if it fails."""
    projects = get_projects()
    selected_project = select_from_list(projects, "Select a Project for Cluster Deletion")
    if not selected_project:
        return

    clusters = get_clusters(selected_project)
    if not clusters:
        return

    cluster_display_list = [f"{name} ({loc})" for name, loc in clusters]
    selected_cluster_display = select_from_list(cluster_display_list, f"Select a Cluster in '{selected_project}' to Delete")
    if not selected_cluster_display:
        return

    selected_index = cluster_display_list.index(selected_cluster_display)
    cluster_name, location = clusters[selected_index]
    location_flag = "--region" if len(location.split('-')) == 2 else "--zone"

    print("\n" + "="*50)
    print(f"⚠️  WARNING: You are about to attempt to delete the GKE cluster:")
    print(f"   Cluster: {cluster_name}")
    print(f"   Project: {selected_project}")
    print("This action is irreversible.")
    print("="*50)

    confirm = input("Type the cluster name to confirm: ")
    if confirm.strip() != cluster_name:
        print("\nConfirmation did not match. Aborting deletion.")
        return

    print(f"\nIssuing delete command for cluster '{cluster_name}'...")
    delete_cmd = [
        "gcloud", "container", "clusters", "delete", cluster_name,
        f"--project={selected_project}", location_flag, location, "--async"
    ]

    run_command(delete_cmd)
    print(f"\n✅ Successfully initiated deletion for cluster '{cluster_name}'.")
    print("Monitor the operation status in the Google Cloud Console or by running:")
    print(f"gcloud container operations list --project={selected_project} --filter=\"targetLink.scope().segment(-1)='{cluster_name}'\"")
    print("\nIf deletion fails again, run 'gke-switch check-orphans' to find blocking resources.")

def check_orphans():
    """Scans for orphaned GCP resources associated with a GKE cluster."""
    projects = get_projects()
    selected_project = select_from_list(projects, "Select a Project to Scan for Orphans")
    if not selected_project:
        return

    clusters = get_clusters(selected_project)
    if not clusters:
        return
        
    cluster_display_list = [f"{name} ({loc})" for name, loc in clusters]
    selected_cluster_display = select_from_list(cluster_display_list, f"Select a Cluster in '{selected_project}' to Scan")
    if not selected_cluster_display:
        return

    selected_index = cluster_display_list.index(selected_cluster_display)
    cluster_name, _ = clusters[selected_index]
    
    # GKE resources are typically prefixed with `gke-{cluster-name}`
    # We can also find the cluster's unique ID for more precise filtering if needed
    cluster_prefix = f"gke-{cluster_name}"

    print(f"\n--- 🔍 Scanning for Orphaned Resources for Cluster: {cluster_name} ---")
    print(f"Using naming prefix: '{cluster_prefix}'")

    # 1. Check Deletion Logs
    print("\n[1/4] Searching for Deletion Error Logs...")
    print("This shows the specific reason the cluster deletion failed.")
    log_cmd = (
        f'gcloud logging read \'resource.type="gke_cluster" '
        f'AND resource.labels.cluster_name="{cluster_name}" '
        f'AND protoPayload.methodName="google.container.v1.ClusterManager.DeleteCluster" '
        f'AND severity=ERROR\' --project={selected_project} --limit=3 '
        '--format="value(protoPayload.status.message, timestamp)"'
    )
    log_result = run_command(log_cmd, shell=True)
    if log_result.stdout.strip():
        print(log_result.stdout)
    else:
        print("No specific deletion error logs found. The issue might be with an underlying resource.")

    # 2. Check Networking Resources
    print("\n[2/4] Scanning for Orphaned Networking Resources (Load Balancers, Firewalls)...")
    print("Look for resources that were created by a Kubernetes Service but not cleaned up.")
    # Check Forwarding Rules (LBs)
    fw_rule_cmd = f"gcloud compute forwarding-rules list --project={selected_project} --filter=\"name~'{cluster_prefix}' OR description~'{cluster_name}'\" --format='table(name, region, target)'"
    print("\n--- Forwarding Rules:")
    fw_result = run_command(fw_rule_cmd, shell=True)
    print(fw_result.stdout or "None found.")
    
    # Check Firewall Rules
    firewall_cmd = f"gcloud compute firewall-rules list --project={selected_project} --filter=\"name~'{cluster_prefix}'\" --format='table(name, direction, priority, targetTags)'"
    print("\n--- Firewall Rules:")
    firewall_result = run_command(firewall_cmd, shell=True)
    print(firewall_result.stdout or "None found.")

    # 3. Check Persistent Disks
    print("\n[3/4] Scanning for Orphaned Persistent Disks...")
    print("Look for disks that were provisioned by a PVC and are no longer attached or needed.")
    disk_cmd = f"gcloud compute disks list --project={selected_project} --filter=\"users~'/instances/gke-{cluster_name}' OR name~'gke-{cluster_name}'\" --format='table(name, sizeGb, status, users)'"
    disk_result = run_command(disk_cmd, shell=True)
    print(disk_result.stdout or "None found.")

    # 4. Final advice
    print("\n[4/4] --- Summary & Next Steps ---")
    print("The lists above show potential orphaned resources linked to your cluster by name.")
    print("1. **Review the Deletion Logs:** The error message from step [1] is the most important clue.")
    print("2. **Inspect Listed Resources:** Carefully check if the resources found in steps [2] and [3] are still needed.")
    print("   - If a resource (e.g., a Load Balancer's forwarding rule) is listed in the deletion error log, it is safe to delete.")
    print("   - You can delete them using 'gcloud compute <resource-type> delete <resource-name> ...'")
    print("3. **Retry Deletion:** After cleaning up the blocking resources, run 'gke-switch force-delete' again.")
    print("4. **Contact Support:** If you cannot identify the blocking resource, contact Google Cloud Support with the log output.")
    print("--- Scan Complete ---")

def interactive_setup():
    """Guides the user through selecting a project and cluster to set up."""
    projects = get_projects()
    selected_project = select_from_list(projects, "Select a Google Cloud Project")
    if not selected_project:
        return

    clusters = get_clusters(selected_project)
    if not clusters:
        return

    # Format for display: "cluster-name (location)"
    cluster_display_list = [f"{name} ({loc})" for name, loc in clusters]
    selected_cluster_display = select_from_list(cluster_display_list, f"Select a GKE Cluster in '{selected_project}'")
    if not selected_cluster_display:
        return

    # Find the original tuple (name, location) from the selected display string
    selected_index = cluster_display_list.index(selected_cluster_display)
    cluster_name, location = clusters[selected_index]

    context_name = get_cluster_credentials(selected_project, cluster_name, location)

    # Update cache
    cache = load_cache()
    # Use a user-friendly alias for the key
    alias = f"{selected_project}/{cluster_name}"
    cache[alias] = context_name
    save_cache(cache)
    
    # Automatically switch to the newly configured context
    run_command(["kubectl", "config", "use-context", context_name])
    print(f"\nSwitched to new context: {context_name}")


def switch_context():
    """Allows the user to switch between cached cluster contexts."""
    cache = load_cache()
    if not cache:
        print("Cache is empty. Run 'setup' to add a cluster first.")
        return

    aliases = list(cache.keys())
    selected_alias = select_from_list(aliases, "Select a Cached Cluster to Switch To")

    if selected_alias:
        context_name = cache[selected_alias]
        print(f"Switching to '{selected_alias}' ({context_name})...")
        run_command(["kubectl", "config", "use-context", context_name])
        print("Successfully switched context.")

def clear_cache():
    """Clears the local cache file."""
    if CACHE_FILE.exists():
        os.remove(CACHE_FILE)
        print(f"Cache file at {CACHE_FILE} has been removed.")
    else:
        print("No cache file to clear.")

def show_help():
    """Prints the help message."""
    print("""
GKE Cluster Switcher

A tool to easily configure and switch between kubectl contexts for GKE clusters
across multiple GCP projects.

Usage:
  gke-switch <command>

Available Commands:
  setup            - Interactively select a project and cluster to configure.
  switch           - Switch between previously configured and cached clusters.
  debug            - Get diagnostic info for a cluster when kubectl fails.
  force-delete     - Attempt to delete a stuck cluster and get debug steps.
  check-orphans    - Scan for orphaned GCP resources linked to a cluster.
  check-finalizers - Check for finalizers on all clusters within a selected project.
  clear-cache      - Remove the cached cluster configuration file.
  help             - Show this help message.
""")

def main():
    """Main function to parse arguments and run the appropriate command."""
    if len(sys.argv) < 2:
        show_help()
        sys.exit(1)

    command = sys.argv[1]

    if command == "setup":
        interactive_setup()
    elif command == "switch":
        switch_context()
    elif command == "debug":
        debug_cluster()
    elif command == "force-delete":
        force_delete_cluster()
    elif command == "check-orphans":
        check_orphans()
    elif command == "check-finalizers":
        check_finalizers()
    elif command == "clear-cache":
        clear_cache()
    elif command == "help":
        show_help()
    else:
        print(f"Unknown command: {command}")
        show_help()
        sys.exit(1)

if __name__ == "__main__":
    main()


