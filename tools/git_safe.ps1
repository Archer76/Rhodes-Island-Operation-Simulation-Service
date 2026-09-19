# tools/git_safe.ps1 —— 提交 / 重置的**结构闸门**（dot-source 使用）
#
# 守什么（一行说清）：**任何 reset / rebase / commit 之前，检查结论必须先赋值给变量，
# 动作只能挂在它后面；且 reset 的目标必须是具体 sha，不许 `HEAD~N`。**
#
# 出处：2026-09-19 后端在本仓用 `git reset --soft HEAD~2` 压缩自己的两笔提交，
# 但同仓另一会话的两笔新提交已在其之上 ⇒ 相对位移被"后来居上"的提交悄悄改义，
# 把**别人的提交移出分支**（用 --soft 故内容未丢，已 `reset --soft <原sha>` 恢复）。
# 同一天还有一次同型事故：提交脚本只看 `git` 退出码、没把"测试全绿"当闸门，
# 于是把一个**编译不过**的测试提交进了历史。
#
# 两次根因是同一个：**判据看得见，但动作没挂在判据后面**。
# 检查写了却不影响动作，等于没检查。此文件把这件事变成结构上的不可能。
#
# 用法：
#   . .\tools\git_safe.ps1
#   $pre = <某个布尔检查的结论>            # 必须先赋值
#   Invoke-GuardedReset -Sha '3bab699' -Precondition $pre -Why '压缩自己的两笔'
#   Invoke-GuardedCommit -Paths @('a.go') -Messages @('标题','正文') -TestsGreen $green

Set-StrictMode -Version Latest

# Assert-Sha：拒绝相对位移与引用式目标。为什么：`HEAD~2` 的含义取决于"此刻 HEAD 是谁"，
# 而共享仓库里"此刻"随时会被别人改；要动哪两笔，就把它们的 sha 写出来。
function Assert-Sha {
    param([Parameter(Mandatory = $true)][string]$Sha,
          [Parameter(Mandatory = $true)][string]$Why)
    if ($Sha -match '^HEAD([~^]|\b)|@\{|^[~^]') {
        throw "拒绝：reset/rebase 目标不许用相对位移（得到 '$Sha'）。请先 git log 取具体 sha。用途：$Why"
    }
    if ($Sha -notmatch '^[0-9a-fA-F]{7,40}$') {
        throw "拒绝：目标不是 sha（得到 '$Sha'）。用途：$Why"
    }
    return $Sha
}

# Invoke-GuardedReset：前提为假则**什么都不做**（不是"做了再修"）。
function Invoke-GuardedReset {
    param([Parameter(Mandatory = $true)][string]$Sha,
          [Parameter(Mandatory = $true)][bool]$Precondition,
          [Parameter(Mandatory = $true)][string]$Why)
    if (-not $Precondition) {
        throw "拒绝：前提不成立，未执行任何动作（用途：$Why）。前提不成立时取消，比做了再修便宜。"
    }
    $target = Assert-Sha -Sha $Sha -Why $Why
    git reset --soft $target
    if ($LASTEXITCODE -ne 0) { throw "reset 失败（退出码 $LASTEXITCODE，用途：$Why）" }
}

# Invoke-GuardedCommit：测试未全绿则拒绝提交；提交必须带路径限定。
function Invoke-GuardedCommit {
    param([Parameter(Mandatory = $true)][string[]]$Paths,
          [Parameter(Mandatory = $true)][string[]]$Messages,
          [Parameter(Mandatory = $true)][bool]$TestsGreen,
          [Parameter(Mandatory = $true)][string]$Why)
    if (-not $TestsGreen) {
        throw "拒绝提交：测试未全绿（用途：$Why）。这正是那次把编译不过的测试提交进历史的成因。"
    }
    if (-not $Paths -or $Paths.Count -eq 0) {
        throw "拒绝提交：必须给路径限定（用途：$Why）。无路径限定的提交会带走别人暂存的文件。"
    }
    # ⚠ 变量名不能叫 $args：那是 PowerShell 的自动变量，赋值会被静默忽略/报错。
    $a = @()
    foreach ($m in $Messages) { $a += @('-m', $m) }
    $a += '--'
    $a += $Paths
    git -c core.safecrlf=false commit -q @a
    if ($LASTEXITCODE -ne 0) { throw "提交失败（退出码 $LASTEXITCODE，用途：$Why）" }
}
