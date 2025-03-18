import os
import shutil

def move_files_to_parent_directory(directory):
    """
    递归地将指定目录下的所有子文件夹中的所有文件移动到该文件的上一级目录。
    :param directory: 要处理的根目录路径
    """
    for foldername, _, filenames in os.walk(directory, topdown=False):
        if foldername == directory:
            continue
        for filename in filenames:
            file_path = os.path.join(foldername, filename)
            destination_path = os.path.join(os.path.dirname(foldername), filename)
            
            # 检查目标路径是否已存在同名文件
            if os.path.exists(destination_path):
                print(f"Skipping {file_path} because {destination_path} already exists.")
                continue
            
            try:
                shutil.move(file_path, destination_path)
            except Exception as e:
                print(f"Error moving {file_path}: {str(e)}")

        # 删除空文件夹
        if not os.listdir(foldername):
            os.rmdir(foldername)

if __name__ == "__main__":
    # 添加二次确认提示
    confirmation = input("This will move all files in subdirectories to the parent directory. Are you sure? ([y]/n): ").strip().lower()
    if confirmation == '' or confirmation == 'y':
        # 调用函数，从当前目录开始处理
        move_files_to_parent_directory(os.getcwd())
    else:
        print("Operation cancelled.")